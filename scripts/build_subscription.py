#!/usr/bin/env python3
"""
VPN Subscription Aggregator & Tester
=====================================
1. Тянет конфиги (vless/vmess/trojan/ss) из sources.txt (в т.ч. Telegram-каналы)
2. Парсит и убирает дубликаты
3. Тестирует КАЖДЫЙ конфиг ДВАЖДЫ через реальный локальный Xray-процесс
   (не просто TCP-хендшейк, а настоящий HTTP-запрос через прокси), чтобы
   отсеять "флаки"-серверы, которые отвечают один раз и потом отваливаются
4. Оставляет только те, что уложились в лимит задержки (--max-latency-ms) ОБА
   раза — то есть только реально быстрые и стабильные
5. Публикует ДВЕ отдельные подписки:
     output/subscription.txt        — обычные конфиги (для WiFi/кабеля)
     output/subscription_white.txt  — конфиги для белых списков (жёсткий
                                       мобильный интернет)
   Разделение задаётся тегом [white] / [regular] перед ссылкой в sources.txt
   или manual.txt. Без тега — по умолчанию "regular".
6. output/report.json — подробный отчёт по каждому конфигу (оба раунда,
   финальная задержка, категория) — для ручной проверки
7. manual.txt — конфиги, добавленные вручную: тестируются (для информации),
   но остаются в подписке всегда, даже если тест не прошёл
8. blacklist.txt — подстроки хостов, которые нужно всегда игнорировать
"""

import argparse
import base64
import html
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

TEST_URL = "https://www.gstatic.com/generate_204"
BASE_SOCKS_PORT = 24000
URI_RE = re.compile(r'(?:vless|vmess|trojan|ss)://[^\s<>"\'\\]+')
CATEGORY_FILENAMES = {"regular": "subscription.txt", "white": "subscription_white.txt"}
TAG_RE = re.compile(r'^\[(\w+)\]\s*(.+)$')


# --------------------------------------------------------------------------
# Загрузка источников
# --------------------------------------------------------------------------

def load_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def load_tagged_lines(path):
    """Строка может начинаться с [white] или [regular] — иначе категория
    по умолчанию 'regular'. Возвращает список (категория, значение)."""
    out = []
    for line in load_lines(path):
        m = TAG_RE.match(line)
        if m:
            out.append((m.group(1).lower(), m.group(2).strip()))
        else:
            out.append(("regular", line))
    return out


def is_telegram_source(url):
    return url.startswith("@") or "t.me/" in url


def normalize_telegram_url(url):
    # поддерживает записи: @channel , t.me/channel , t.me/s/channel
    if url.startswith("@"):
        return f"https://t.me/s/{url[1:]}"
    if "t.me/s/" in url:
        return url
    prefix, _, channel = url.partition("t.me/")
    return f"{prefix}t.me/s/{channel}"


def fetch_telegram_channel(url):
    """Публичный веб-превью Telegram-канала (t.me/s/<channel>) — без бота и
    без логина. Достаёт только конфиги, вставленные в текст сообщения.
    Файлы-вложения (.txt/.yaml), приложенные отдельным документом, так
    получить нельзя — Telegram не отдаёт их содержимое в HTML-превью."""
    tg_url = normalize_telegram_url(url)
    try:
        r = requests.get(tg_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = html.unescape(r.text)  # Telegram отдаёт &amp; вместо & в HTML
        uris = URI_RE.findall(text)
        return [u.rstrip('.,;)]}"\'') for u in uris]
    except Exception as e:
        print(f"[!] telegram source failed: {tg_url} -> {e}", file=sys.stderr)
        return []


def fetch_source(url):
    if is_telegram_source(url):
        return fetch_telegram_channel(url)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        text = r.text.strip()
        # подписки почти всегда целиком base64
        try:
            pad = "=" * (-len(text) % 4)
            decoded = base64.b64decode(text + pad).decode("utf-8", errors="ignore")
            if "://" in decoded:
                text = decoded
        except Exception:
            pass
        return [l.strip() for l in text.splitlines() if "://" in l]
    except Exception as e:
        print(f"[!] source failed: {url} -> {e}", file=sys.stderr)
        return []


# --------------------------------------------------------------------------
# Парсинг URI -> (ключ дедупликации, outbound JSON для Xray)
# --------------------------------------------------------------------------

def _b64_json(payload):
    pad = "=" * (-len(payload) % 4)
    return json.loads(base64.b64decode(payload + pad).decode("utf-8", errors="ignore"))


def parse_vless_trojan(uri, proto):
    # vless://uuid@host:port?params#remark   (trojan аналогично, вместо uuid - пароль)
    body = uri.split("://", 1)[1]
    if "#" in body:
        body, remark = body.split("#", 1)
    else:
        remark = ""
    userinfo, hostport_q = body.split("@", 1)
    if "?" in hostport_q:
        hostport, query = hostport_q.split("?", 1)
    else:
        hostport, query = hostport_q, ""
    host, port = hostport.rsplit(":", 1)
    port = int(port)
    q = dict(urllib.parse.parse_qsl(query))

    network = q.get("type", "tcp")
    security = q.get("security", "none")

    stream = {"network": network}
    if security == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "serverName": q.get("sni", ""),
            "fingerprint": q.get("fp", "chrome"),
            "publicKey": q.get("pbk", ""),
            "shortId": q.get("sid", ""),
            "spiderX": q.get("spx", ""),
        }
    elif security == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = {
            "serverName": q.get("sni", host),
            "fingerprint": q.get("fp", "chrome"),
            "allowInsecure": False,
        }
        if q.get("alpn"):
            stream["tlsSettings"]["alpn"] = q["alpn"].split(",")
    else:
        stream["security"] = "none"

    if network == "ws":
        stream["wsSettings"] = {
            "path": q.get("path", "/"),
            "headers": {"Host": q.get("host", host)},
        }
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": q.get("serviceName", "")}

    if proto == "vless":
        user = {"id": userinfo, "encryption": q.get("encryption", "none")}
        if q.get("flow"):
            user["flow"] = q["flow"]
        outbound = {
            "protocol": "vless",
            "settings": {"vnext": [{"address": host, "port": port, "users": [user]}]},
            "streamSettings": stream,
        }
    else:  # trojan
        outbound = {
            "protocol": "trojan",
            "settings": {"servers": [{"address": host, "port": port, "password": userinfo}]},
            "streamSettings": stream,
        }

    return {"proto": proto, "host": host, "port": port, "remark": urllib.parse.unquote(remark), "raw": uri}, outbound


def parse_vmess(uri):
    payload = uri.split("://", 1)[1]
    data = _b64_json(payload)
    host = data["add"]
    port = int(data["port"])
    net = data.get("net", "tcp")
    stream = {"network": net}
    if str(data.get("tls", "")).lower() == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = {"serverName": data.get("sni") or data.get("host") or host}
    if net == "ws":
        stream["wsSettings"] = {"path": data.get("path", "/"), "headers": {"Host": data.get("host", host)}}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": data.get("path", "")}

    outbound = {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": host, "port": port,
                "users": [{"id": data["id"], "alterId": int(data.get("aid", 0) or 0), "security": "auto"}],
            }]
        },
        "streamSettings": stream,
    }
    meta = {"proto": "vmess", "host": host, "port": port, "remark": data.get("ps", ""), "raw": uri}
    return meta, outbound


def parse_ss(uri):
    body = uri.split("://", 1)[1]
    remark = ""
    if "#" in body:
        body, remark = body.split("#", 1)
    if "@" in body:
        userinfo, hostport = body.split("@", 1)
        pad = "=" * (-len(userinfo) % 4)
        try:
            userinfo = base64.b64decode(userinfo + pad).decode("utf-8")
        except Exception:
            pass
        method, password = userinfo.split(":", 1)
    else:
        pad = "=" * (-len(body) % 4)
        decoded = base64.b64decode(body + pad).decode("utf-8")
        methodpass, hostport = decoded.split("@", 1)
        method, password = methodpass.split(":", 1)
    host, port = hostport.rsplit(":", 1)
    port = int(port)
    outbound = {
        "protocol": "shadowsocks",
        "settings": {"servers": [{"address": host, "port": port, "method": method, "password": password}]},
    }
    meta = {"proto": "ss", "host": host, "port": port, "remark": urllib.parse.unquote(remark), "raw": uri}
    return meta, outbound


def parse_uri(uri):
    try:
        scheme = uri.split("://", 1)[0]
        if scheme in ("vless", "trojan"):
            return parse_vless_trojan(uri, scheme)
        if scheme == "vmess":
            return parse_vmess(uri)
        if scheme == "ss":
            return parse_ss(uri)
    except Exception as e:
        print(f"[!] parse failed for {uri[:60]}...: {e}", file=sys.stderr)
    return None


# --------------------------------------------------------------------------
# Тестирование через реальный Xray-процесс (2 раунда: пинг -> пауза -> пинг+скорость)
# --------------------------------------------------------------------------

SPEED_TEST_URL = "https://speed.cloudflare.com/__down?bytes=524288"  # 512 KB, официальный speed-test эндпоинт Cloudflare
SPEED_TEST_BYTES = 524288


def build_xray_config(outbound, socks_port):
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "listen": "127.0.0.1", "port": socks_port, "protocol": "socks",
            "settings": {"udp": False},
        }],
        "outbounds": [outbound],
    }


def test_one(xray_bin, meta, outbound, socks_port, timeout, speed_timeout, want_speed):
    """Поднимает Xray с этим outbound-ом, реально ходит через него в интернет.
    want_speed=False -> только задержка (быстрый раунд-1 отсев).
    want_speed=True  -> задержка + реальная скорость закачки (финальный раунд)."""
    cfg = build_xray_config(outbound, socks_port)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        cfg_path = f.name

    proc = None
    try:
        proc = subprocess.Popen(
            [xray_bin, "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)  # даём Xray время подняться
        if proc.poll() is not None:
            return {**meta, "ok": False, "error": "xray_exited", "latency_ms": None, "speed_kbps": None}

        proxies = {
            "http": f"socks5h://127.0.0.1:{socks_port}",
            "https": f"socks5h://127.0.0.1:{socks_port}",
        }
        t0 = time.time()
        r = requests.get(TEST_URL, proxies=proxies, timeout=timeout)
        latency_ms = round((time.time() - t0) * 1000)
        ok = r.status_code in (200, 204)
        result = {**meta, "ok": ok, "error": None if ok else f"http_{r.status_code}",
                  "latency_ms": latency_ms, "speed_kbps": None}

        if ok and want_speed:
            try:
                downloaded = 0
                t1 = time.time()
                with requests.get(SPEED_TEST_URL, proxies=proxies, timeout=speed_timeout, stream=True) as r2:
                    for chunk in r2.iter_content(chunk_size=32768):
                        downloaded += len(chunk)
                        if downloaded >= SPEED_TEST_BYTES or time.time() - t1 > speed_timeout:
                            break
                elapsed = time.time() - t1
                if downloaded > 0 and elapsed > 0:
                    result["speed_kbps"] = round((downloaded / 1024) / elapsed, 1)
                else:
                    result["ok"] = False
                    result["error"] = "speed_test_empty"
            except Exception as e:
                result["ok"] = False
                result["error"] = f"speed_test_failed:{str(e)[:60]}"

        return result
    except Exception as e:
        return {**meta, "ok": False, "error": str(e)[:120], "latency_ms": None, "speed_kbps": None}
    finally:
        if proc is not None:
            proc.kill()
            proc.wait(timeout=5)
        try:
            os.unlink(cfg_path)
        except OSError:
            pass


def run_round(xray_bin, items, workers, timeout, speed_timeout, want_speed):
    """items: список (meta, outbound). Возвращает список результатов теста."""
    port_pool = queue.Queue()
    for i in range(workers):
        port_pool.put(BASE_SOCKS_PORT + i)

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for meta, outbound in items:
            port = port_pool.get()
            fut = pool.submit(test_one, xray_bin, meta, outbound, port, timeout, speed_timeout, want_speed)
            futures[fut] = port
        for fut in as_completed(futures):
            results.append(fut.result())
            port_pool.put(futures[fut])
    return results


# --------------------------------------------------------------------------
# Загрузка одной категории (normal / white)
# --------------------------------------------------------------------------

def load_category(sources_path, manual_path, category, blacklist):
    sources = load_lines(sources_path)
    manual_uris = load_lines(manual_path)

    raw_uris = list(manual_uris)
    for src in sources:
        raw_uris.extend(fetch_source(src))
    print(f"[i] [{category}] raw configs collected: {len(raw_uris)}")

    manual_set = set(manual_uris)
    parsed = []
    seen = set()
    for uri in raw_uris:
        result = parse_uri(uri)
        if not result:
            continue
        meta, outbound = result
        if any(b in meta["host"] for b in blacklist):
            continue
        key = (meta["proto"], meta["host"], meta["port"])
        if key in seen:
            continue
        seen.add(key)
        meta["category"] = category
        meta["pinned"] = uri in manual_set
        parsed.append((meta, outbound))
    print(f"[i] [{category}] unique configs after dedupe: {len(parsed)}")
    return parsed


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="sources.txt")
    ap.add_argument("--manual", default="manual.txt")
    ap.add_argument("--sources-white", default="sources_whitelist.txt")
    ap.add_argument("--manual-white", default="manual_whitelist.txt")
    ap.add_argument("--blacklist", default="blacklist.txt")
    ap.add_argument("--xray-bin", default="./xray")
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--timeout", type=float, default=6.0, help="таймаут пинг-проверки (сек)")
    ap.add_argument("--speed-timeout", type=float, default=8.0, help="таймаут проверки скорости (сек)")
    ap.add_argument("--round-gap", type=float, default=30.0, help="пауза между раундом-1 и раундом-2 (сек)")
    ap.add_argument("--max-latency-ms", type=float, default=350.0, help="макс. допустимый пинг")
    ap.add_argument("--min-speed-kbps", type=float, default=250.0, help="мин. скорость закачки, КБ/с")
    ap.add_argument("--max-output", type=int, default=20, help="сколько конфигов оставлять в каждой подписке")
    ap.add_argument("--outdir", default="output")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    blacklist = load_lines(args.blacklist)

    normal_items = load_category(args.sources, args.manual, "normal", blacklist)
    white_items = load_category(args.sources_white, args.manual_white, "white", blacklist)
    all_items = normal_items + white_items

    if not all_items:
        print("[!] Нет ни одного конфига для проверки — проверь sources.txt / sources_whitelist.txt")
        return

    # --- Раунд 1: быстрый отсев только по задержке ---
    print(f"[i] Раунд 1 (пинг): проверяю {len(all_items)} конфигов...")
    round1 = run_round(args.xray_bin, all_items, args.workers, args.timeout, args.speed_timeout, want_speed=False)
    round1_ok = {(r["proto"], r["host"], r["port"]) for r in round1
                 if r["ok"] and r["latency_ms"] is not None and r["latency_ms"] <= args.max_latency_ms}
    print(f"[i] Раунд 1: прошли {len(round1_ok)}/{len(all_items)} (латency <= {args.max_latency_ms} мс)")

    survivors = [(m, o) for (m, o) in all_items if (m["proto"], m["host"], m["port"]) in round1_ok]

    # --- Пауза перед раундом 2, чтобы не засчитать "везение на секунду" ---
    if survivors and args.round_gap > 0:
        print(f"[i] Жду {args.round_gap:.0f} сек перед раундом 2...")
        time.sleep(args.round_gap)

    # --- Раунд 2: задержка + реальная скорость закачки, только для выживших ---
    print(f"[i] Раунд 2 (пинг+скорость): проверяю {len(survivors)} конфигов...")
    round2 = run_round(args.xray_bin, survivors, args.workers, args.timeout, args.speed_timeout, want_speed=True)

    final_ok = [
        r for r in round2
        if r["ok"]
        and r["latency_ms"] is not None and r["latency_ms"] <= args.max_latency_ms
        and r["speed_kbps"] is not None and r["speed_kbps"] >= args.min_speed_kbps
    ]
    print(f"[i] Раунд 2: подтвердили стабильность и скорость {len(final_ok)}/{len(survivors)}")

    # сортировка: сначала быстрее скорость закачки, при равенстве - меньше пинг
    final_ok.sort(key=lambda r: (-r["speed_kbps"], r["latency_ms"]))

    # полный отчёт для ручной проверки (все раунды, все конфиги)
    report = {
        "round1": sorted(round1, key=lambda r: (not r["ok"], r["latency_ms"] or 9999)),
        "round2": sorted(round2, key=lambda r: (not r["ok"], -(r["speed_kbps"] or 0))),
        "settings": {
            "max_latency_ms": args.max_latency_ms,
            "min_speed_kbps": args.min_speed_kbps,
            "max_output": args.max_output,
        },
    }
    with open(os.path.join(args.outdir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    for category in ("normal", "white"):
        pinned = [m for (m, o) in (normal_items if category == "normal" else white_items) if m["pinned"]]
        pinned_keys = {(m["proto"], m["host"], m["port"]) for m in pinned}

        auto_best = [r for r in final_ok if r["category"] == category
                     and (r["proto"], r["host"], r["port"]) not in pinned_keys]
        auto_best = auto_best[: args.max_output]

        final_lines = [m["raw"] for m in pinned] + [r["raw"] for r in auto_best]
        sub_b64 = base64.b64encode("\n".join(final_lines).encode("utf-8")).decode("utf-8")

        suffix = "" if category == "normal" else "_whitelist"
        sub_path = os.path.join(args.outdir, f"subscription{suffix}.txt")
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write(sub_b64)

        print(f"[i] [{category}] опубликовано: {len(pinned)} закреплённых + {len(auto_best)} лучших "
              f"-> {sub_path}")
        if not pinned and not auto_best:
            print(f"[!] [{category}] подписка пустая — попробуй смягчить --max-latency-ms/--min-speed-kbps "
                  f"или добавь больше источников")


if __name__ == "__main__":
    main()
