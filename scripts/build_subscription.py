#!/usr/bin/env python3

"""
VPN Subscription Aggregator & Tester
====================================

Логика:

1. Загружает конфиги из:
   - sources.txt
   - manual.txt
   - sources_whitelist.txt
   - manual_whitelist.txt

2. Декодирует base64-подписки.

3. Парсит:
   - VLESS
   - VMess
   - Trojan
   - Shadowsocks

4. Удаляет дубликаты.

5. Применяет blacklist к:
   - host
   - remark
   - полному URI

6. Проверяет КАЖДЫЙ конфиг через Xray в два раунда:
   - раунд 1: реальный HTTP-запрос + latency
   - раунд 2: latency + реальная скорость загрузки

7. Только прошедшие оба раунда могут попасть в подписку.

8. Для каждой категории выбираются лучшие конфиги:
   - сначала высокая скорость
   - затем низкая задержка
   - максимум max-output

9. Исходные названия конфигов полностью заменяются на:
   Tuskone VPN 01
   Tuskone VPN 02
   ...

10. Публикуются две отдельные подписки:
    output/subscription.txt
    output/subscription_whitelist.txt

11. output/report.json содержит подробный отчёт.
"""

import argparse
import base64
import html
import json
import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


TEST_URL = "https://www.gstatic.com/generate_204"

SPEED_TEST_URL = (
    "https://speed.cloudflare.com/__down?bytes=524288"
)

SPEED_TEST_BYTES = 524288

BASE_SOCKS_PORT = 24000

URI_RE = re.compile(
    r'(?:vless|vmess|trojan|ss)://[^\s<>"\'\\]+'
)


# --------------------------------------------------------------------------
# Загрузка файлов
# --------------------------------------------------------------------------

def load_lines(path):
    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip()
            and not line.strip().startswith("#")
        ]


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------

def is_telegram_source(url):
    return url.startswith("@") or "t.me/" in url


def normalize_telegram_url(url):
    # @channel
    if url.startswith("@"):
        return f"https://t.me/s/{url[1:]}"

    # уже t.me/s/channel
    if "t.me/s/" in url:
        return url

    # t.me/channel
    prefix, _, channel = url.partition("t.me/")

    return f"{prefix}t.me/s/{channel}"


def fetch_telegram_channel(url):
    """
    Загружает публичное web-превью Telegram-канала
    и пытается достать конфиги из текста сообщений.
    """

    tg_url = normalize_telegram_url(url)

    try:
        response = requests.get(
            tg_url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        text = html.unescape(response.text)

        uris = URI_RE.findall(text)

        return [
            uri.rstrip(".,;)]}\"'")
            for uri in uris
        ]

    except Exception as e:
        print(
            f"[!] telegram source failed: {tg_url} -> {e}",
            file=sys.stderr
        )

        return []


# --------------------------------------------------------------------------
# Источники
# --------------------------------------------------------------------------

def fetch_source(url):
    if is_telegram_source(url):
        return fetch_telegram_channel(url)

    try:
        response = requests.get(
            url,
            timeout=15
        )

        response.raise_for_status()

        text = response.text.strip()

        # Подписка часто приходит целиком в base64.
        try:
            padding = "=" * (-len(text) % 4)

            decoded = base64.b64decode(
                text + padding
            ).decode(
                "utf-8",
                errors="ignore"
            )

            if "://" in decoded:
                text = decoded

        except Exception:
            pass

        return [
            line.strip()
            for line in text.splitlines()
            if "://" in line
        ]

    except Exception as e:
        print(
            f"[!] source failed: {url} -> {e}",
            file=sys.stderr
        )

        return []


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _b64_json(payload):
    padding = "=" * (-len(payload) % 4)

    return json.loads(
        base64.b64decode(
            payload + padding
        ).decode(
            "utf-8",
            errors="ignore"
        )
    )


def parse_vless_trojan(uri, proto):
    """
    VLESS / Trojan
    """

    body = uri.split("://", 1)[1]

    if "#" in body:
        body, remark = body.split("#", 1)
    else:
        remark = ""

    userinfo, hostport_q = body.split("@", 1)

    if "?" in hostport_q:
        hostport, query = hostport_q.split("?", 1)
    else:
        hostport = hostport_q
        query = ""

    host, port = hostport.rsplit(":", 1)

    port = int(port)

    q = dict(
        urllib.parse.parse_qsl(query)
    )

    network = q.get("type", "tcp")

    security = q.get(
        "security",
        "none"
    )

    stream = {
        "network": network
    }

    # Reality
    if security == "reality":
        stream["security"] = "reality"

        stream["realitySettings"] = {
            "serverName": q.get(
                "sni",
                ""
            ),
            "fingerprint": q.get(
                "fp",
                "chrome"
            ),
            "publicKey": q.get(
                "pbk",
                ""
            ),
            "shortId": q.get(
                "sid",
                ""
            ),
            "spiderX": q.get(
                "spx",
                ""
            ),
        }

    # TLS
    elif security == "tls":
        stream["security"] = "tls"

        stream["tlsSettings"] = {
            "serverName": q.get(
                "sni",
                host
            ),
            "fingerprint": q.get(
                "fp",
                "chrome"
            ),
            "allowInsecure": False,
        }

        if q.get("alpn"):
            stream["tlsSettings"]["alpn"] = (
                q["alpn"].split(",")
            )

    # Без шифрования
    else:
        stream["security"] = "none"

    # WebSocket
    if network == "ws":
        stream["wsSettings"] = {
            "path": q.get(
                "path",
                "/"
            ),
            "headers": {
                "Host": q.get(
                    "host",
                    host
                )
            },
        }

    # gRPC
    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": q.get(
                "serviceName",
                ""
            )
        }

    # VLESS
    if proto == "vless":
        user = {
            "id": userinfo,
            "encryption": q.get(
                "encryption",
                "none"
            )
        }

        if q.get("flow"):
            user["flow"] = q["flow"]

        outbound = {
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": host,
                        "port": port,
                        "users": [
                            user
                        ]
                    }
                ]
            },
            "streamSettings": stream,
        }

    # Trojan
    else:
        outbound = {
            "protocol": "trojan",
            "settings": {
                "servers": [
                    {
                        "address": host,
                        "port": port,
                        "password": userinfo
                    }
                ]
            },
            "streamSettings": stream,
        }

    meta = {
        "proto": proto,
        "host": host,
        "port": port,
        "remark": urllib.parse.unquote(
            remark
        ),
        "raw": uri,
    }

    return meta, outbound


def parse_vmess(uri):
    """
    VMess
    """

    payload = uri.split(
        "://",
        1
    )[1]

    data = _b64_json(payload)

    host = data["add"]

    port = int(data["port"])

    network = data.get(
        "net",
        "tcp"
    )

    stream = {
        "network": network
    }

    if str(
        data.get(
            "tls",
            ""
        )
    ).lower() == "tls":

        stream["security"] = "tls"

        stream["tlsSettings"] = {
            "serverName": (
                data.get("sni")
                or data.get("host")
                or host
            )
        }

    if network == "ws":
        stream["wsSettings"] = {
            "path": data.get(
                "path",
                "/"
            ),
            "headers": {
                "Host": data.get(
                    "host",
                    host
                )
            }
        }

    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": data.get(
                "path",
                ""
            )
        }

    outbound = {
        "protocol": "vmess",
        "settings": {
            "vnext": [
                {
                    "address": host,
                    "port": port,
                    "users": [
                        {
                            "id": data["id"],
                            "alterId": int(
                                data.get(
                                    "aid",
                                    0
                                ) or 0
                            ),
                            "security": "auto"
                        }
                    ],
                }
            ]
        },
        "streamSettings": stream,
    }

    meta = {
        "proto": "vmess",
        "host": host,
        "port": port,
        "remark": data.get(
            "ps",
            ""
        ),
        "raw": uri,
    }

    return meta, outbound


def parse_ss(uri):
    """
    Shadowsocks
    """

    body = uri.split(
        "://",
        1
    )[1]

    remark = ""

    if "#" in body:
        body, remark = body.split(
            "#",
            1
        )

    if "@" in body:
        userinfo, hostport = body.split(
            "@",
            1
        )

        padding = "=" * (
            -len(userinfo) % 4
        )

        try:
            userinfo = base64.b64decode(
                userinfo + padding
            ).decode("utf-8")

        except Exception:
            pass

        method, password = userinfo.split(
            ":",
            1
        )

    else:
        padding = "=" * (
            -len(body) % 4
        )

        decoded = base64.b64decode(
            body + padding
        ).decode("utf-8")

        methodpass, hostport = decoded.split(
            "@",
            1
        )

        method, password = methodpass.split(
            ":",
            1
        )

    host, port = hostport.rsplit(
        ":",
        1
    )

    port = int(port)

    outbound = {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": port,
                    "method": method,
                    "password": password
                }
            ]
        }
    }

    meta = {
        "proto": "ss",
        "host": host,
        "port": port,
        "remark": urllib.parse.unquote(
            remark
        ),
        "raw": uri,
    }

    return meta, outbound


def parse_uri(uri):
    try:
        scheme = uri.split(
            "://",
            1
        )[0].lower()

        if scheme in (
            "vless",
            "trojan"
        ):
            return parse_vless_trojan(
                uri,
                scheme
            )

        if scheme == "vmess":
            return parse_vmess(uri)

        if scheme == "ss":
            return parse_ss(uri)

    except Exception as e:
        print(
            f"[!] parse failed for {uri[:80]}...: {e}",
            file=sys.stderr
        )

    return None


# --------------------------------------------------------------------------
# Blacklist
# --------------------------------------------------------------------------

def is_blacklisted(meta, blacklist):
    """
    Проверяем blacklist не только по host,
    а по host + remark + полному URI.
    """

    searchable_text = " ".join(
        [
            meta.get("host", ""),
            meta.get("remark", ""),
            meta.get("raw", "")
        ]
    ).lower()

    for entry in blacklist:
        entry = entry.strip().lower()

        if not entry:
            continue

        if entry in searchable_text:
            return True

    return False


# --------------------------------------------------------------------------
# Xray
# --------------------------------------------------------------------------

def build_xray_config(
    outbound,
    socks_port
):
    return {
        "log": {
            "loglevel": "none"
        },

        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {
                    "udp": False
                }
            }
        ],

        "outbounds": [
            outbound
        ]
    }


def test_one(
    xray_bin,
    meta,
    outbound,
    socks_port,
    timeout,
    speed_timeout,
    want_speed
):
    """
    Реальная проверка через Xray.

    want_speed=False:
        latency

    want_speed=True:
        latency + speed
    """

    cfg = build_xray_config(
        outbound,
        socks_port
    )

    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".json",
        delete=False
    ) as f:
        json.dump(
            cfg,
            f
        )

        cfg_path = f.name

    proc = None
    watchdog = None

    try:
        proc = subprocess.Popen(
            [
                xray_bin,
                "run",
                "-c",
                cfg_path
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        hard_deadline = (
            timeout
            + (
                speed_timeout
                if want_speed
                else 0
            )
            + 8
        )

        proc_ref = proc

        watchdog = threading.Timer(
            hard_deadline,
            lambda: (
                proc_ref.kill()
                if proc_ref.poll() is None
                else None
            )
        )

        watchdog.daemon = True

        watchdog.start()

        time.sleep(1.0)

        if proc.poll() is not None:
            return {
                **meta,
                "ok": False,
                "error": "xray_exited",
                "latency_ms": None,
                "speed_kbps": None
            }

        proxies = {
            "http": (
                f"socks5h://127.0.0.1:{socks_port}"
            ),
            "https": (
                f"socks5h://127.0.0.1:{socks_port}"
            ),
        }

        # --------------------------------------------------------------
        # Latency test
        # --------------------------------------------------------------

        t0 = time.time()

        response = requests.get(
            TEST_URL,
            proxies=proxies,
            timeout=timeout
        )

        latency_ms = round(
            (
                time.time() - t0
            ) * 1000
        )

        ok = response.status_code in (
            200,
            204
        )

        result = {
            **meta,
            "ok": ok,
            "error": (
                None
                if ok
                else f"http_{response.status_code}"
            ),
            "latency_ms": latency_ms,
            "speed_kbps": None
        }

        # --------------------------------------------------------------
        # Speed test
        # --------------------------------------------------------------

        if ok and want_speed:
            try:
                downloaded = 0

                t1 = time.time()

                with requests.get(
                    SPEED_TEST_URL,
                    proxies=proxies,
                    timeout=speed_timeout,
                    stream=True
                ) as speed_response:

                    for chunk in speed_response.iter_content(
                        chunk_size=32768
                    ):
                        if not chunk:
                            continue

                        downloaded += len(chunk)

                        if (
                            downloaded
                            >= SPEED_TEST_BYTES
                        ):
                            break

                        if (
                            time.time()
                            - t1
                            > speed_timeout
                        ):
                            break

                elapsed = (
                    time.time()
                    - t1
                )

                if (
                    downloaded > 0
                    and elapsed > 0
                ):
                    speed_kbps = round(
                        (
                            downloaded
                            / 1024
                        )
                        / elapsed,
                        1
                    )

                    result["speed_kbps"] = speed_kbps

                else:
                    result["ok"] = False

                    result["error"] = (
                        "speed_test_empty"
                    )

            except Exception as e:
                result["ok"] = False

                result["error"] = (
                    "speed_test_failed:"
                    + str(e)[:60]
                )

        return result

    except Exception as e:
        return {
            **meta,
            "ok": False,
            "error": str(e)[:120],
            "latency_ms": None,
            "speed_kbps": None
        }

    finally:
        if watchdog is not None:
            watchdog.cancel()

        if proc is not None:
            try:
                proc.kill()
                proc.wait(
                    timeout=5
                )
            except Exception:
                pass

        try:
            os.unlink(
                cfg_path
            )
        except OSError:
            pass


def _test_one_with_port(
    xray_bin,
    meta,
    outbound,
    port_pool,
    timeout,
    speed_timeout,
    want_speed
):
    port = port_pool.get()

    try:
        return test_one(
            xray_bin,
            meta,
            outbound,
            port,
            timeout,
            speed_timeout,
            want_speed
        )

    finally:
        port_pool.put(port)


def run_round(
    xray_bin,
    items,
    workers,
    timeout,
    speed_timeout,
    want_speed
):
    """
    Тестирует список конфигов параллельно.
    """

    port_pool = queue.Queue()

    for i in range(workers):
        port_pool.put(
            BASE_SOCKS_PORT + i
        )

    results = []

    with ThreadPoolExecutor(
        max_workers=workers
    ) as pool:

        futures = [
            pool.submit(
                _test_one_with_port,
                xray_bin,
                meta,
                outbound,
                port_pool,
                timeout,
                speed_timeout,
                want_speed
            )
            for meta, outbound in items
        ]

        for future in as_completed(
            futures
        ):
            results.append(
                future.result()
            )

    return results


# --------------------------------------------------------------------------
# Категории
# --------------------------------------------------------------------------

def load_category(
    sources_path,
    manual_path,
    category,
    blacklist
):
    """
    Загружает источники и manual-файл.

    ВАЖНО:
    manual-файл НЕ имеет никаких привилегий.
    Он проходит те же тесты, что и конфиги
    из обычных источников.
    """

    sources = load_lines(
        sources_path
    )

    manual_uris = load_lines(
        manual_path
    )

    # --------------------------------------------------------------
    # Все конфиги собираем в единый список
    # --------------------------------------------------------------

    raw_uris = []

    for source in sources:
        raw_uris.extend(
            fetch_source(source)
        )

    raw_uris.extend(
        manual_uris
    )

    print(
        f"[i] [{category}] raw configs collected: "
        f"{len(raw_uris)}"
    )

    # --------------------------------------------------------------
    # Парсинг + blacklist + dedupe
    # --------------------------------------------------------------

    parsed = []

    seen = set()

    blacklist_count = 0
    parse_failed_count = 0
    duplicate_count = 0

    for uri in raw_uris:

        result = parse_uri(uri)

        if not result:
            parse_failed_count += 1
            continue

        meta, outbound = result

        # ----------------------------------------------------------
        # BLACKLIST
        # ----------------------------------------------------------

        if is_blacklisted(
            meta,
            blacklist
        ):
            blacklist_count += 1
            continue

        # ----------------------------------------------------------
        # Более разумный ключ дедупликации
        # ----------------------------------------------------------

        key = (
            meta["proto"],
            meta["host"].lower(),
            meta["port"]
        )

        if key in seen:
            duplicate_count += 1
            continue

        seen.add(key)

        meta["category"] = category

        # Никаких pinned!
        meta["pinned"] = False

        parsed.append(
            (
                meta,
                outbound
            )
        )

    print(
        f"[i] [{category}] unique configs after filtering: "
        f"{len(parsed)}"
    )

    print(
        f"[i] [{category}] blacklist removed: "
        f"{blacklist_count}"
    )

    print(
        f"[i] [{category}] parse failed: "
        f"{parse_failed_count}"
    )

    print(
        f"[i] [{category}] duplicates removed: "
        f"{duplicate_count}"
    )

    return parsed


# --------------------------------------------------------------------------
# Переименование
# --------------------------------------------------------------------------

def rename_uri(
    uri,
    index
):
    """
    Полностью удаляет старое название #remark
    и ставит новое.
    """

    base_uri = uri.split(
        "#",
        1
    )[0]

    return (
        f"{base_uri}"
        f"#Tuskone%20VPN%20{index:02d}"
    )


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():

    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--sources",
        default="sources.txt"
    )

    ap.add_argument(
        "--manual",
        default="manual.txt"
    )

    ap.add_argument(
        "--sources-white",
        default="sources_whitelist.txt"
    )

    ap.add_argument(
        "--manual-white",
        default="manual_whitelist.txt"
    )

    ap.add_argument(
        "--blacklist",
        default="blacklist.txt"
    )

    ap.add_argument(
        "--xray-bin",
        default="./xray"
    )

    ap.add_argument(
        "--workers",
        type=int,
        default=15
    )

    ap.add_argument(
        "--timeout",
        type=float,
        default=6.0,
        help="таймаут пинг-проверки"
    )

    ap.add_argument(
        "--speed-timeout",
        type=float,
        default=8.0,
        help="таймаут проверки скорости"
    )

    ap.add_argument(
        "--round-gap",
        type=float,
        default=30.0,
        help="пауза между раундами"
    )

    ap.add_argument(
        "--max-latency-ms",
        type=float,
        default=250.0,
        help="максимальная задержка"
    )

    ap.add_argument(
        "--min-speed-kbps",
        type=float,
        default=1000.0,
        help="минимальная скорость"
    )

    ap.add_argument(
        "--max-output",
        type=int,
        default=10,
        help="сколько конфигов оставлять"
    )

    ap.add_argument(
        "--outdir",
        default="output"
    )

    ap.add_argument(
        "--skip-test",
        action="store_true",
        help=(
            "опубликовать manual-файлы без теста; "
            "не используется обычным workflow"
        )
    )

    args = ap.parse_args()

    os.makedirs(
        args.outdir,
        exist_ok=True
    )

    blacklist = load_lines(
        args.blacklist
    )

    # Защита от зависания сетевых запросов
    socket.setdefaulttimeout(
        max(
            args.timeout,
            args.speed_timeout
        ) + 5
    )

    # ------------------------------------------------------------------
    # SKIP TEST
    # ------------------------------------------------------------------

    if args.skip_test:
        print(
            "[i] --skip-test включён."
        )

        for category in (
            "normal",
            "white"
        ):

            if category == "normal":
                manual_path = args.manual
            else:
                manual_path = args.manual_white

            manual_uris = load_lines(
                manual_path
            )

            seen = set()

            final_lines = []

            for uri in manual_uris:

                result = parse_uri(uri)

                if not result:
                    print(
                        f"[!] [{category}] "
                        f"не разобрано: "
                        f"{uri[:80]}..."
                    )
                    continue

                meta, _ = result

                if is_blacklisted(
                    meta,
                    blacklist
                ):
                    continue

                key = (
                    meta["proto"],
                    meta["host"].lower(),
                    meta["port"]
                )

                if key in seen:
                    continue

                seen.add(key)

                final_lines.append(
                    uri
                )

            sub_b64 = base64.b64encode(
                "\n".join(
                    final_lines
                ).encode("utf-8")
            ).decode("utf-8")

            suffix = (
                ""
                if category == "normal"
                else "_whitelist"
            )

            sub_path = os.path.join(
                args.outdir,
                f"subscription{suffix}.txt"
            )

            with open(
                sub_path,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(
                    sub_b64
                )

            print(
                f"[i] [{category}] "
                f"опубликовано без теста: "
                f"{len(final_lines)} -> {sub_path}"
            )

        return

    # ------------------------------------------------------------------
    # Загрузка двух категорий
    # ------------------------------------------------------------------

    normal_items = load_category(
        args.sources,
        args.manual,
        "normal",
        blacklist
    )

    white_items = load_category(
        args.sources_white,
        args.manual_white,
        "white",
        blacklist
    )

    all_items = (
        normal_items
        + white_items
    )

    if not all_items:
        print(
            "[!] Нет ни одного конфига "
            "для проверки."
        )
        return

    # ------------------------------------------------------------------
    # RAUND 1
    # ------------------------------------------------------------------

    print(
        f"[i] Раунд 1 (latency): "
        f"проверяю {len(all_items)} конфигов..."
    )

    round1 = run_round(
        args.xray_bin,
        all_items,
        args.workers,
        args.timeout,
        args.speed_timeout,
        want_speed=False
    )

    round1_ok = {
        (
            result["proto"],
            result["host"],
            result["port"]
        )
        for result in round1
        if (
            result["ok"]
            and result["latency_ms"] is not None
            and result["latency_ms"]
            <= args.max_latency_ms
        )
    }

    print(
        f"[i] Раунд 1: "
        f"прошли {len(round1_ok)}/"
        f"{len(all_items)} "
        f"(latency <= "
        f"{args.max_latency_ms} ms)"
    )

    survivors = [
        (
            meta,
            outbound
        )

        for meta, outbound in all_items

        if (
            meta["proto"],
            meta["host"],
            meta["port"]
        ) in round1_ok
    ]

    # ------------------------------------------------------------------
    # Пауза
    # ------------------------------------------------------------------

    if (
        survivors
        and args.round_gap > 0
    ):
        print(
            f"[i] Жду "
            f"{args.round_gap:.0f} сек "
            f"перед вторым раундом..."
        )

        time.sleep(
            args.round_gap
        )

    # ------------------------------------------------------------------
    # RAUND 2
    # ------------------------------------------------------------------

    print(
        f"[i] Раунд 2 "
        f"(latency + speed): "
        f"проверяю "
        f"{len(survivors)} конфигов..."
    )

    round2 = run_round(
        args.xray_bin,
        survivors,
        args.workers,
        args.timeout,
        args.speed_timeout,
        want_speed=True
    )

    # ------------------------------------------------------------------
    # Финальная фильтрация
    # ------------------------------------------------------------------

    final_ok = [
        result

        for result in round2

        if (
            result["ok"]

            and result["latency_ms"] is not None

            and result["latency_ms"]
            <= args.max_latency_ms

            and result["speed_kbps"] is not None

            and result["speed_kbps"]
            >= args.min_speed_kbps
        )
    ]

    print(
        f"[i] Раунд 2: "
        f"подтвердили "
        f"{len(final_ok)}/"
        f"{len(survivors)} "
        f"конфигов."
    )

    # ------------------------------------------------------------------
    # Сортировка
    # ------------------------------------------------------------------

    final_ok.sort(
        key=lambda result: (
            -result["speed_kbps"],
            result["latency_ms"]
        )
    )

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    report = {
        "round1": sorted(
            round1,
            key=lambda result: (
                not result["ok"],
                result["latency_ms"]
                if result["latency_ms"]
                is not None
                else 999999
            )
        ),

        "round2": sorted(
            round2,
            key=lambda result: (
                not result["ok"],
                -(result["speed_kbps"] or 0)
            )
        ),

        "settings": {
            "max_latency_ms": (
                args.max_latency_ms
            ),
            "min_speed_kbps": (
                args.min_speed_kbps
            ),
            "max_output": (
                args.max_output
            ),
            "workers": (
                args.workers
            ),
            "round_gap": (
                args.round_gap
            )
        }
    }

    report_path = os.path.join(
        args.outdir,
        "report.json"
    )

    with open(
        report_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=2
        )

    # ------------------------------------------------------------------
    # Создание подписок
    # ------------------------------------------------------------------

    for category in (
        "normal",
        "white"
    ):

        # Только успешно прошедшие тесты.
        category_best = [
            result

            for result in final_ok

            if result["category"]
            == category
        ]

        # Ограничиваем количество.
        category_best = category_best[
            :args.max_output
        ]

        # --------------------------------------------------------------
        # Переименовываем КАЖДЫЙ конфиг
        # --------------------------------------------------------------

        final_lines = [
            rename_uri(
                result["raw"],
                index
            )

            for index, result
            in enumerate(
                category_best,
                start=1
            )
        ]

        # --------------------------------------------------------------
        # Base64
        # --------------------------------------------------------------

        sub_b64 = base64.b64encode(
            "\n".join(
                final_lines
            ).encode("utf-8")
        ).decode("utf-8")

        suffix = (
            ""
            if category == "normal"
            else "_whitelist"
        )

        sub_path = os.path.join(
            args.outdir,
            f"subscription{suffix}.txt"
        )

        with open(
            sub_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(
                sub_b64
            )

        print(
            f"[i] [{category}] "
            f"опубликовано "
            f"{len(final_lines)} "
            f"лучших конфигов "
            f"-> {sub_path}"
        )

        if not final_lines:
            print(
                f"[!] [{category}] "
                f"подписка пустая. "
                f"Все конфиги не прошли "
                f"строгую проверку."
            )


if __name__ == "__main__":
    main()
