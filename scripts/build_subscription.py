#!/usr/bin/env python3

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


# ==========================================================================
# НАСТРОЙКИ
# ==========================================================================

TEST_URL = "https://www.gstatic.com/generate_204"

SPEED_TEST_URL = (
    "https://speed.cloudflare.com/__down?bytes=524288"
)

SPEED_TEST_BYTES = 524288

BASE_SOCKS_PORT = 24000

URI_RE = re.compile(
    r'(?:vless|vmess|trojan|ss)://[^\s<>"\'\\]+'
)


# ==========================================================================
# СТРАНЫ
# ==========================================================================

COUNTRY_NAMES_RU = {
    "DE": "Германия",
    "FR": "Франция",
    "NL": "Нидерланды",
    "FI": "Финляндия",
    "GB": "Великобритания",
    "UK": "Великобритания",
    "US": "США",
    "CA": "Канада",
    "PL": "Польша",
    "CZ": "Чехия",
    "SK": "Словакия",
    "AT": "Австрия",
    "CH": "Швейцария",
    "BE": "Бельгия",
    "SE": "Швеция",
    "NO": "Норвегия",
    "DK": "Дания",
    "ES": "Испания",
    "PT": "Португалия",
    "IT": "Италия",
    "RO": "Румыния",
    "BG": "Болгария",
    "HU": "Венгрия",
    "RS": "Сербия",
    "UA": "Украина",
    "LT": "Литва",
    "LV": "Латвия",
    "EE": "Эстония",
    "IS": "Исландия",
    "IE": "Ирландия",
    "LU": "Люксембург",
    "MD": "Молдова",
    "TR": "Турция",
    "GE": "Грузия",
    "AM": "Армения",
    "AZ": "Азербайджан",
    "KZ": "Казахстан",
    "UZ": "Узбекистан",
    "KG": "Кыргызстан",
    "JP": "Япония",
    "KR": "Южная Корея",
    "SG": "Сингапур",
    "HK": "Гонконг",
    "TW": "Тайвань",
    "IN": "Индия",
    "IL": "Израиль",
    "AE": "ОАЭ",
    "AU": "Австралия",
    "NZ": "Новая Зеландия",
    "BR": "Бразилия",
    "AR": "Аргентина",
    "CL": "Чили",
    "MX": "Мексика",
    "ZA": "ЮАР",
    "RU": "Россия",
}


COUNTRY_FLAGS = {}

for code in COUNTRY_NAMES_RU:
    if len(code) == 2:
        COUNTRY_FLAGS[code] = (
            chr(ord(code[0]) + 127397)
            + chr(ord(code[1]) + 127397)
        )


COUNTRY_ALIASES = {
    "германия": "DE",
    "germany": "DE",
    "deutschland": "DE",

    "франция": "FR",
    "france": "FR",

    "нидерланды": "NL",
    "нидерланд": "NL",
    "netherlands": "NL",
    "holland": "NL",

    "финляндия": "FI",
    "finland": "FI",

    "великобритания": "GB",
    "англия": "GB",
    "uk": "GB",
    "united kingdom": "GB",
    "england": "GB",
    "britain": "GB",

    "сша": "US",
    "usa": "US",
    "united states": "US",
    "america": "US",
    "америка": "US",

    "канада": "CA",
    "canada": "CA",

    "польша": "PL",
    "poland": "PL",

    "чехия": "CZ",
    "czech": "CZ",
    "czechia": "CZ",

    "австрия": "AT",
    "austria": "AT",

    "швейцария": "CH",
    "switzerland": "CH",

    "бельгия": "BE",
    "belgium": "BE",

    "швеция": "SE",
    "sweden": "SE",

    "норвегия": "NO",
    "norway": "NO",

    "дания": "DK",
    "denmark": "DK",

    "испания": "ES",
    "spain": "ES",

    "португалия": "PT",
    "portugal": "PT",

    "италия": "IT",
    "italy": "IT",

    "румыния": "RO",
    "romania": "RO",

    "болгария": "BG",
    "bulgaria": "BG",

    "венгрия": "HU",
    "hungary": "HU",

    "сербия": "RS",
    "serbia": "RS",

    "украина": "UA",
    "ukraine": "UA",

    "литва": "LT",
    "lithuania": "LT",

    "латвия": "LV",
    "latvia": "LV",

    "эстония": "EE",
    "estonia": "EE",

    "турция": "TR",
    "turkey": "TR",

    "грузия": "GE",
    "georgia": "GE",

    "армения": "AM",
    "armenia": "AM",

    "азербайджан": "AZ",
    "azerbaijan": "AZ",

    "казахстан": "KZ",
    "kazakhstan": "KZ",

    "узбекистан": "UZ",
    "uzbekistan": "UZ",

    "кыргызстан": "KG",
    "kyrgyzstan": "KG",
    "kyrgyz": "KG",

    "япония": "JP",
    "japan": "JP",

    "корея": "KR",
    "южная корея": "KR",
    "south korea": "KR",
    "korea": "KR",

    "сингапур": "SG",
    "singapore": "SG",

    "гонконг": "HK",
    "hong kong": "HK",

    "тайвань": "TW",
    "taiwan": "TW",

    "индия": "IN",
    "india": "IN",

    "израиль": "IL",
    "israel": "IL",

    "оаэ": "AE",
    "uae": "AE",
    "united arab emirates": "AE",

    "австралия": "AU",
    "australia": "AU",

    "новая зеландия": "NZ",
    "new zealand": "NZ",

    "бразилия": "BR",
    "brazil": "BR",

    "аргентина": "AR",
    "argentina": "AR",

    "чили": "CL",
    "chile": "CL",

    "мексика": "MX",
    "mexico": "MX",

    "юар": "ZA",
    "south africa": "ZA",

    "россия": "RU",
    "russia": "RU",
}


# ==========================================================================
# ЗАГРУЗКА
# ==========================================================================

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


# ==========================================================================
# TELEGRAM
# ==========================================================================

def is_telegram_source(url):
    return url.startswith("@") or "t.me/" in url


def normalize_telegram_url(url):
    if url.startswith("@"):
        return f"https://t.me/s/{url[1:]}"

    if "t.me/s/" in url:
        return url

    prefix, _, channel = url.partition("t.me/")

    return f"{prefix}t.me/s/{channel}"


def fetch_telegram_channel(url):
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

        text = html.unescape(
            response.text
        )

        uris = URI_RE.findall(
            text
        )

        return [
            uri.rstrip(
                ".,;)]}\"'"
            )
            for uri in uris
        ]

    except Exception as e:
        print(
            f"[!] Telegram source failed: "
            f"{tg_url} -> {e}",
            file=sys.stderr
        )

        return []


# ==========================================================================
# ИСТОЧНИКИ
# ==========================================================================

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
            f"[!] Source failed: "
            f"{url} -> {e}",
            file=sys.stderr
        )

        return []


# ==========================================================================
# PARSING
# ==========================================================================

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
    body = uri.split(
        "://",
        1
    )[1]

    if "#" in body:
        body, remark = body.split(
            "#",
            1
        )
    else:
        remark = ""

    userinfo, hostport_q = body.split(
        "@",
        1
    )

    if "?" in hostport_q:
        hostport, query = hostport_q.split(
            "?",
            1
        )
    else:
        hostport = hostport_q
        query = ""

    host, port = hostport.rsplit(
        ":",
        1
    )

    port = int(port)

    q = dict(
        urllib.parse.parse_qsl(
            query
        )
    )

    network = q.get(
        "type",
        "tcp"
    )

    security = q.get(
        "security",
        "none"
    )

    stream = {
        "network": network
    }

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

    else:
        stream["security"] = "none"

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

    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": q.get(
                "serviceName",
                ""
            )
        }

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
    payload = uri.split(
        "://",
        1
    )[1]

    data = _b64_json(
        payload
    )

    host = data["add"]

    port = int(
        data["port"]
    )

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
            f"[!] Parse failed for "
            f"{uri[:80]}... -> {e}",
            file=sys.stderr
        )

    return None


# ==========================================================================
# BLACKLIST
# ==========================================================================

def is_blacklisted(
    meta,
    blacklist
):
    searchable = " ".join(
        [
            meta.get(
                "host",
                ""
            ),
            meta.get(
                "remark",
                ""
            ),
            meta.get(
                "raw",
                ""
            )
        ]
    ).lower()

    for item in blacklist:
        item = item.strip().lower()

        if not item:
            continue

        if item in searchable:
            return True

    return False


# ==========================================================================
# ОБХОДЫ WHITE LIST
# ==========================================================================

def is_bypass_config(meta):
    text = (
        f"{meta.get('remark', '')} "
        f"{meta.get('raw', '')}"
    ).lower()

    bypass_words = (
        "обход",
        "bypass",
        "white-list-bypass",
        "whitelist-bypass",
        "white list bypass",
    )

    return any(
        word in text
        for word in bypass_words
    )


# ==========================================================================
# XRAY
# ==========================================================================

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


def http_probe(
    proxies,
    timeout
):
    started = time.time()

    response = requests.get(
        TEST_URL,
        proxies=proxies,
        timeout=timeout
    )

    latency = round(
        (
            time.time()
            - started
        ) * 1000
    )

    return (
        response.status_code in (
            200,
            204
        ),
        latency,
        response.status_code
    )


def test_one(
    xray_bin,
    meta,
    outbound,
    socks_port,
    timeout,
    speed_timeout,
    want_speed
):
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
            stderr=subprocess.DEVNULL
        )

        hard_deadline = (
            timeout
            + speed_timeout
            + 15
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
                "speed_kbps": None,
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
        # ПЕРВЫЙ ПРОБНИК
        # --------------------------------------------------------------

        ok1, latency1, status1 = http_probe(
            proxies,
            timeout
        )

        if not ok1:
            return {
                **meta,
                "ok": False,
                "error": f"http_{status1}",
                "latency_ms": latency1,
                "speed_kbps": None,
            }

        if not want_speed:
            return {
                **meta,
                "ok": True,
                "error": None,
                "latency_ms": latency1,
                "speed_kbps": None,
            }

        # --------------------------------------------------------------
        # ВТОРОЙ ПРОБНИК
        # --------------------------------------------------------------

        time.sleep(0.2)

        ok2, latency2, status2 = http_probe(
            proxies,
            timeout
        )

        if not ok2:
            return {
                **meta,
                "ok": False,
                "error": f"second_http_{status2}",
                "latency_ms": latency1,
                "speed_kbps": None,
            }

        average_latency = round(
            (
                latency1
                + latency2
            ) / 2
        )

        # --------------------------------------------------------------
        # SPEED TEST
        # --------------------------------------------------------------

        downloaded = 0

        started = time.time()

        try:
            with requests.get(
                SPEED_TEST_URL,
                proxies=proxies,
                timeout=speed_timeout,
                stream=True
            ) as response:

                for chunk in response.iter_content(
                    chunk_size=32768
                ):
                    if not chunk:
                        continue

                    downloaded += len(
                        chunk
                    )

                    if downloaded >= SPEED_TEST_BYTES:
                        break

                    if (
                        time.time()
                        - started
                        > speed_timeout
                    ):
                        break

        except Exception as e:
            return {
                **meta,
                "ok": False,
                "error": (
                    "speed_test_failed:"
                    + str(e)[:80]
                ),
                "latency_ms": average_latency,
                "speed_kbps": None,
            }

        elapsed = (
            time.time()
            - started
        )

        if (
            downloaded <= 0
            or elapsed <= 0
        ):
            return {
                **meta,
                "ok": False,
                "error": "speed_test_empty",
                "latency_ms": average_latency,
                "speed_kbps": None,
            }

        speed_kbps = round(
            (
                downloaded / 1024
            ) / elapsed,
            1
        )

        return {
            **meta,
            "ok": True,
            "error": None,
            "latency_ms": average_latency,
            "speed_kbps": speed_kbps,
        }

    except Exception as e:
        return {
            **meta,
            "ok": False,
            "error": str(e)[:120],
            "latency_ms": None,
            "speed_kbps": None,
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
        port_pool.put(
            port
        )


def run_round(
    xray_bin,
    items,
    workers,
    timeout,
    speed_timeout,
    want_speed
):
    port_pool = queue.Queue()

    for i in range(workers):
        port_pool.put(
            BASE_SOCKS_PORT + i
        )

    results = []

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = [
            executor.submit(
                _test_one_with_port,
                xray_bin,
                meta,
                outbound,
                port_pool,
                timeout,
                speed_timeout,
                want_speed
            )

            for meta, outbound
            in items
        ]

        for future in as_completed(
            futures
        ):
            results.append(
                future.result()
            )

    return results


# ==========================================================================
# СТРАНА
# ==========================================================================

def detect_country_from_text(
    text
):
    text = (
        text
        .replace("_", " ")
        .replace("-", " ")
        .lower()
    )

    for alias, code in sorted(
        COUNTRY_ALIASES.items(),
        key=lambda x: len(x[0]),
        reverse=True
    ):
        if alias in text:
            return code

    # Флаги
    for code, flag in COUNTRY_FLAGS.items():
        if flag in text:
            return code

    return None


def resolve_country_ip(
    host,
    cache
):
    host = host.strip()

    if host in cache:
        return cache[host]

    try:
        ip = socket.gethostbyname(
            host
        )

        response = requests.get(
            f"https://ipwho.is/{ip}",
            timeout=4
        )

        data = response.json()

        if data.get("success") is False:
            cache[host] = None
            return None

        country_code = (
            data.get("country_code")
            or ""
        ).upper()

        if len(country_code) != 2:
            cache[host] = None
            return None

        cache[host] = country_code

        return country_code

    except Exception:
        cache[host] = None
        return None


def assign_countries(
    results,
    country_cache
):
    for result in results:
        code = detect_country_from_text(
            result.get(
                "remark",
                ""
            )
        )

        if code is None:
            code = detect_country_from_text(
                result.get(
                    "raw",
                    ""
                )
            )

        if code is None:
            code = resolve_country_ip(
                result.get(
                    "host",
                    ""
                ),
                country_cache
            )

        if code is None:
            result["country_code"] = "UN"
            result["country_name"] = (
                "Неизвестная страна"
            )
            result["country_flag"] = "🌐"

        else:
            result["country_code"] = code

            result["country_name"] = (
                COUNTRY_NAMES_RU.get(
                    code,
                    code
                )
            )

            result["country_flag"] = (
                COUNTRY_FLAGS.get(
                    code,
                    "🌐"
                )
            )


# ==========================================================================
# НАЗВАНИЕ
# ==========================================================================

def make_country_title(
    result
):
    return (
        f"{result['country_flag']} "
        f"{result['country_name']}"
    )


def rename_uri(
    uri,
    title
):
    base_uri = uri.split(
        "#",
        1
    )[0]

    encoded_title = urllib.parse.quote(
        title,
        safe=""
    )

    return (
        f"{base_uri}"
        f"#{encoded_title}"
    )


# ==========================================================================
# ЗАГРУЗКА КАТЕГОРИИ
# ==========================================================================

def load_category(
    sources_path,
    manual_path,
    category,
    blacklist
):
    sources = load_lines(
        sources_path
    )

    manual_uris = load_lines(
        manual_path
    )

    raw_uris = []

    # Сначала реальные источники
    for source in sources:
        raw_uris.extend(
            fetch_source(source)
        )

    # Manual НЕ получает привилегий.
    # Он просто добавляет конфиги в общий пул.
    raw_uris.extend(
        manual_uris
    )

    print(
        f"[i] [{category}] "
        f"raw configs: "
        f"{len(raw_uris)}"
    )

    parsed = []

    seen = set()

    skipped_blacklist = 0
    skipped_parse = 0
    skipped_duplicate = 0

    for uri in raw_uris:

        result = parse_uri(
            uri
        )

        if not result:
            skipped_parse += 1
            continue

        meta, outbound = result

        if is_blacklisted(
            meta,
            blacklist
        ):
            skipped_blacklist += 1
            continue

        key = (
            meta["proto"],
            meta["host"].lower(),
            meta["port"]
        )

        if key in seen:
            skipped_duplicate += 1
            continue

        seen.add(
            key
        )

        meta["category"] = category

        meta["is_bypass"] = (
            category == "white"
            and is_bypass_config(
                meta
            )
        )

        parsed.append(
            (
                meta,
                outbound
            )
        )

    print(
        f"[i] [{category}] "
        f"unique: {len(parsed)}"
    )

    print(
        f"[i] [{category}] "
        f"blacklist: {skipped_blacklist}"
    )

    print(
        f"[i] [{category}] "
        f"parse failed: {skipped_parse}"
    )

    print(
        f"[i] [{category}] "
        f"duplicates: {skipped_duplicate}"
    )

    bypass_count = sum(
        1
        for meta, _
        in parsed
        if meta.get(
            "is_bypass",
            False
        )
    )

    if category == "white":
        print(
            f"[i] [{category}] "
            f"bypass configs found: "
            f"{bypass_count}"
        )

    return parsed


# ==========================================================================
# SCORE
# ==========================================================================

def calculate_score(
    speed_kbps,
    latency_ms
):
    if (
        speed_kbps is None
        or latency_ms is None
    ):
        return 0.0

    # Чем выше скорость — тем лучше.
    # Чем ниже latency — тем лучше.
    #
    # +50 нужен, чтобы маленькие различия
    # в latency не делали рейтинг слишком резким.

    return round(
        (
            speed_kbps
            * 250
            / (latency_ms + 50)
        ),
        2
    )


# ==========================================================================
# MAIN
# ==========================================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sources",
        default="sources.txt"
    )

    parser.add_argument(
        "--manual",
        default="manual.txt"
    )

    parser.add_argument(
        "--sources-white",
        default="sources_whitelist.txt"
    )

    parser.add_argument(
        "--manual-white",
        default="manual_whitelist.txt"
    )

    parser.add_argument(
        "--blacklist",
        default="blacklist.txt"
    )

    parser.add_argument(
        "--xray-bin",
        default="./xray"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=20
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=6.0
    )

    parser.add_argument(
        "--speed-timeout",
        type=float,
        default=8.0
    )

    parser.add_argument(
        "--round-gap",
        type=float,
        default=30.0
    )

    # Обычные конфиги
    parser.add_argument(
        "--max-latency-ms",
        type=float,
        default=250.0
    )

    parser.add_argument(
        "--min-speed-kbps",
        type=float,
        default=1000.0
    )

    # Сколько обычных конфигов публиковать
    parser.add_argument(
        "--max-output",
        type=int,
        default=10
    )

    # Специальный лимит для обходов
    parser.add_argument(
        "--bypass-output",
        type=int,
        default=3
    )

    # Более мягкий, но всё ещё строгий
    # порог именно для обходов whitelist
    parser.add_argument(
        "--bypass-max-latency-ms",
        type=float,
        default=500.0
    )

    parser.add_argument(
        "--bypass-min-speed-kbps",
        type=float,
        default=200.0
    )

    parser.add_argument(
        "--outdir",
        default="output"
    )

    args = parser.parse_args()

    os.makedirs(
        args.outdir,
        exist_ok=True
    )

    blacklist = load_lines(
        args.blacklist
    )

    socket.setdefaulttimeout(
        max(
            args.timeout,
            args.speed_timeout
        ) + 5
    )

    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Пропустить тесты Xray"
    )

    # ------------------------------------------------------------------
    # LOAD
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
            "[!] Нет конфигов."
        )
        return

    # ------------------------------------------------------------------
    # TESTING / SKIP TEST
    # ------------------------------------------------------------------

    if args.skip_test:
        print("[i] ⚡ Включен --skip-test. Пропускаем тесты Xray...")
        final_ok = []
        for meta, outbound in all_items:
            final_ok.append({
                **meta,
                "ok": True,
                "error": None,
                "latency_ms": 10,
                "speed_kbps": 1000.0,
                "quality_score": 100.0,
            })

    else:
        # --------------------------------------------------------------
        # ROUND 1
        # --------------------------------------------------------------

        print(
            f"[i] Раунд 1: "
            f"проверяю "
            f"{len(all_items)} конфигов..."
        )

        round1 = run_round(
            args.xray_bin,
            all_items,
            args.workers,
            args.timeout,
            args.speed_timeout,
            False
        )

    round1_ok = set()

    for result in round1:

        if not result.get(
            "ok",
            False
        ):
            continue

        latency = result.get(
            "latency_ms"
        )

        if latency is None:
            continue

        is_bypass = result.get(
            "is_bypass",
            False
        )

        # Для bypass отдельный предел latency
        if is_bypass:
            allowed_latency = (
                args.bypass_max_latency_ms
            )
        else:
            allowed_latency = (
                args.max_latency_ms
            )

        if latency <= allowed_latency:
            round1_ok.add(
                (
                    result["proto"],
                    result["host"],
                    result["port"]
                )
            )

    print(
        f"[i] Раунд 1: "
        f"прошли "
        f"{len(round1_ok)}/"
        f"{len(all_items)}"
    )

    survivors = [
        (
            meta,
            outbound
        )

        for meta, outbound
        in all_items

        if (
            meta["proto"],
            meta["host"],
            meta["port"]
        ) in round1_ok
    ]

    if (
        survivors
        and args.round_gap > 0
    ):
        print(
            f"[i] Жду "
            f"{args.round_gap:.0f} сек..."
        )

        time.sleep(
            args.round_gap
        )

    # ------------------------------------------------------------------
    # ROUND 2
    # ------------------------------------------------------------------

    print(
        f"[i] Раунд 2: "
        f"latency + speed: "
        f"{len(survivors)} конфигов..."
    )

    round2 = run_round(
        args.xray_bin,
        survivors,
        args.workers,
        args.timeout,
        args.speed_timeout,
        True
    )

    # ------------------------------------------------------------------
    # FINAL FILTER
    # ------------------------------------------------------------------

    final_ok = []

    for result in round2:

        if not result.get(
            "ok",
            False
        ):
            continue

        latency = result.get(
            "latency_ms"
        )

        speed = result.get(
            "speed_kbps"
        )

        if (
            latency is None
            or speed is None
        ):
            continue

        is_bypass = result.get(
            "is_bypass",
            False
        )

        if is_bypass:
            max_latency = (
                args.bypass_max_latency_ms
            )

            min_speed = (
                args.bypass_min_speed_kbps
            )

        else:
            max_latency = (
                args.max_latency_ms
            )

            min_speed = (
                args.min_speed_kbps
            )

        if latency > max_latency:
            continue

        if speed < min_speed:
            continue

        result["quality_score"] = (
            calculate_score(
                speed,
                latency
            )
        )

        final_ok.append(
            result
        )

    # ------------------------------------------------------------------
    # COUNTRY DETECTION
    # ------------------------------------------------------------------

    country_cache = {}

    assign_countries(
        final_ok,
        country_cache
    )

    # ------------------------------------------------------------------
    # SORT
    # ------------------------------------------------------------------

    final_ok.sort(
        key=lambda x: (
            -x.get(
                "quality_score",
                0
            ),
            x.get(
                "latency_ms",
                999999
            ),
            -x.get(
                "speed_kbps",
                0
            )
        )
    )

    # ------------------------------------------------------------------
    # REPORT
    # ------------------------------------------------------------------

    report = {
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
            "bypass_output": (
                args.bypass_output
            ),
            "bypass_max_latency_ms": (
                args.bypass_max_latency_ms
            ),
            "bypass_min_speed_kbps": (
                args.bypass_min_speed_kbps
            ),
        },

        "round1": round1,

        "round2": round2,

        "final": final_ok,
    }

    with open(
        os.path.join(
            args.outdir,
            "report.json"
        ),
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
    # BUILD SUBSCRIPTIONS
    # ------------------------------------------------------------------

    for category in (
        "normal",
        "white"
    ):

        category_results = [
            result
            for result in final_ok
            if result.get(
                "category"
            ) == category
        ]

        if category == "normal":

            selected = [
                result
                for result
                in category_results
                if not result.get(
                    "is_bypass",
                    False
                )
            ]

            selected = selected[
                :args.max_output
            ]

        else:

            # ----------------------------------------------------------
            # WHITE:
            # обычные конфиги + отдельная квота обходов
            # ----------------------------------------------------------

            regular = [
                result
                for result
                in category_results
                if not result.get(
                    "is_bypass",
                    False
                )
            ]

            bypass = [
                result
                for result
                in category_results
                if result.get(
                    "is_bypass",
                    False
                )
            ]

            bypass = bypass[
                :args.bypass_output
            ]

            regular_slots = max(
                0,
                args.max_output
                - len(bypass)
            )

            regular = regular[
                :regular_slots
            ]

            selected = (
                regular
                + bypass
            )

            selected.sort(
                key=lambda x: (
                    -x.get(
                        "quality_score",
                        0
                    ),
                    x.get(
                        "latency_ms",
                        999999
                    )
                )
            )

        # --------------------------------------------------------------
        # НАЗВАНИЯ
        # --------------------------------------------------------------

        final_lines = []

        for result in selected:

            title = make_country_title(
                result
            )

            final_lines.append(
                rename_uri(
                    result["raw"],
                    title
                )
            )

        # --------------------------------------------------------------
        # BASE64
        # --------------------------------------------------------------

        # Заголовки подписки (метаданные для клиентов)
        headers = [
            "#profile-title: base64:VHVza29uZSBWUE4=",
            "#profile-update-interval: 1",
        ]

        # Объединяем заголовки и конфиги
        content_lines = headers + final_lines

        sub_b64 = base64.b64encode(
            "\n".join(
                content_lines
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

        # --------------------------------------------------------------
        # СТАТИСТИКА ПО СТРАНАМ
        # --------------------------------------------------------------

        countries = {}

        for result in selected:

            country_title = (
                f"{result['country_flag']} "
                f"{result['country_name']}"
            )

            countries[country_title] = (
                countries.get(
                    country_title,
                    0
                )
                + 1
            )

        print("")
        print(
            "=================================================="
        )

        print(
            f"[i] [{category}] "
            f"ИТОГ: "
            f"{len(selected)} конфигов"
        )

        print(
            f"[i] [{category}] "
            f"Файл: {sub_path}"
        )

        print(
            f"[i] [{category}] "
            f"Страны:"
        )

        for country, count in sorted(
            countries.items(),
            key=lambda x: (
                -x[1],
                x[0]
            )
        ):
            print(
                f"    {country}: "
                f"{count}"
            )

        if category == "white":

            bypass_selected = sum(
                1
                for result
                in selected
                if result.get(
                    "is_bypass",
                    False
                )
            )

            print(
                f"[i] [{category}] "
                f"Обходов в подписке: "
                f"{bypass_selected}"
            )

        print(
            "=================================================="
        )
        print("")


if __name__ == "__main__":
    main()
