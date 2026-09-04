#!/usr/bin/env python3

import argparse
import base64
import datetime
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
    r'(?:vless|trojan|hysteria2|hy2)://[^\s<>"\'\\]+'
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
                # По умолчанию — SNI, а не IP/адрес подключения: при
                # доменной маскировке (CDN-фронтинг) Host обязан совпадать
                # с доменом, иначе сервер не поймёт, куда роутить запрос.
                "Host": q.get(
                    "host"
                ) or q.get(
                    "sni"
                ) or host
            },
        }

    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": q.get(
                "serviceName",
                ""
            )
        }

    elif network == "xhttp":
        stream["xhttpSettings"] = {
            "host": q.get("host", ""),
            "path": q.get("path", "/"),
            "mode": q.get("mode", "auto"),
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
                "Host": (
                    data.get("host")
                    or data.get("sni")
                    or host
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


def parse_hysteria2(uri):
    # hysteria2://auth@host:port/?insecure=1&sni=example.com&alpn=h3#remark
    # (hy2:// — тот же формат, короткий алиас схемы)
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

    auth, hostport_q = body.split(
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

    # отбрасываем возможный путь (/...) перед query
    hostport = hostport.split("/", 1)[0]

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

    insecure = q.get(
        "insecure",
        "0"
    ) in ("1", "true", "True")

    sni = (
        q.get("sni")
        or q.get("peer")
        or host
    )

    alpn = q.get(
        "alpn",
        "h3"
    ).split(",")

    outbound = {
        "protocol": "hysteria",
        "settings": {
            "version": 2,
            "address": host,
            "port": port,
        },
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                "serverName": sni,
                "allowInsecure": insecure,
                "alpn": alpn,
            },
            "hysteriaSettings": {
                "version": 2,
                "auth": auth,
                "udpIdleTimeout": 60,
            },
        },
    }

    meta = {
        "proto": "hysteria2",
        "host": host,
        "port": port,
        "remark": urllib.parse.unquote(
            remark
        ),
        "raw": uri,
    }

    return meta, outbound


# --------------------------------------------------------------------------
# ОБРАТНОЕ ПРЕОБРАЗОВАНИЕ: полный Xray/V2Ray JSON-конфиг клиента -> URI
# --------------------------------------------------------------------------
# Позволяет вставлять в manual.txt / manual_whitelist.txt не только готовые
# vless://... ссылки, но и целый JSON-конфиг (например, экспортированный
# из клиента с настройками роутинга) — достаём оттуда только сервер.
# ВАЖНО: правила маршрутизации (routing/dns из такого JSON) НЕ переносятся —
# формат подписки физически не умеет их передавать, это настройка каждого
# приложения отдельно, а не подписки.

def _vless_outbound_to_uri(outbound, remarks):
    try:
        settings = outbound.get("settings", {})
        vnext = (settings.get("vnext") or [{}])[0]
        address = vnext.get("address")
        port = vnext.get("port")
        user = (vnext.get("users") or [{}])[0]
        uid = user.get("id")

        if not (address and port and uid):
            return None

        stream = outbound.get("streamSettings", {})
        network = stream.get("network", "tcp")
        security = stream.get("security", "none")

        params = {
            "encryption": user.get("encryption", "none"),
            "type": network,
            "security": security,
        }

        if user.get("flow"):
            params["flow"] = user["flow"]

        if security == "reality":
            rs = stream.get("realitySettings", {})
            params["sni"] = rs.get("serverName", "")
            params["pbk"] = rs.get("publicKey", "")
            params["sid"] = rs.get("shortId", "")
            if rs.get("fingerprint"):
                params["fp"] = rs["fingerprint"]
            if rs.get("spiderX"):
                params["spx"] = rs["spiderX"]

        elif security == "tls":
            ts = stream.get("tlsSettings", {})
            if ts.get("serverName"):
                params["sni"] = ts["serverName"]
            if ts.get("fingerprint"):
                params["fp"] = ts["fingerprint"]
            if ts.get("alpn"):
                params["alpn"] = ",".join(ts["alpn"])

        if network == "ws":
            ws = stream.get("wsSettings", {})
            if ws.get("path"):
                params["path"] = ws["path"]
            ws_host = (ws.get("headers") or {}).get("Host")
            if ws_host:
                params["host"] = ws_host

        elif network == "grpc":
            gs = stream.get("grpcSettings", {})
            if gs.get("serviceName"):
                params["serviceName"] = gs["serviceName"]

        elif network == "xhttp":
            # он же SplitHTTP — новый транспорт, без path/host/mode
            # соединение просто не установится
            xs = stream.get("xhttpSettings", {})
            if xs.get("path"):
                params["path"] = xs["path"]
            if xs.get("host"):
                params["host"] = xs["host"]
            if xs.get("mode"):
                params["mode"] = xs["mode"]
            # xmux (extra) — тонкая настройка производительности, у нас нет
            # подтверждённого стандарта кодирования в URI, сознательно
            # не переносим, чтобы не сгенерировать невалидную ссылку

        query = urllib.parse.urlencode({
            k: v for k, v in params.items() if v not in (None, "")
        })

        frag = urllib.parse.quote(remarks)

        return f"vless://{uid}@{address}:{port}?{query}#{frag}"

    except Exception:
        return None


def _hysteria_outbound_to_uri(outbound, remarks):
    try:
        settings = outbound.get("settings", {})
        address = settings.get("address")
        port = settings.get("port")

        stream = outbound.get("streamSettings", {})
        hs = stream.get("hysteriaSettings", {})
        auth = hs.get("auth", "")

        ts = stream.get("tlsSettings", {})
        sni = ts.get("serverName", "")
        insecure = "1" if ts.get("allowInsecure") else "0"
        alpn = ",".join(ts.get("alpn") or ["h3"])

        if not (address and port and auth):
            return None

        query = urllib.parse.urlencode({
            "insecure": insecure,
            "sni": sni,
            "alpn": alpn,
        })

        frag = urllib.parse.quote(remarks)

        return f"hysteria2://{auth}@{address}:{port}/?{query}#{frag}"

    except Exception:
        return None


def _trojan_outbound_to_uri(outbound, remarks):
    try:
        settings = outbound.get("settings", {})
        server = (settings.get("servers") or [{}])[0]
        address = server.get("address")
        port = server.get("port")
        password = server.get("password")

        if not (address and port and password):
            return None

        stream = outbound.get("streamSettings", {})
        network = stream.get("network", "tcp")
        security = stream.get("security", "tls")

        params = {
            "type": network,
            "security": security,
        }

        if security == "tls":
            ts = stream.get("tlsSettings", {})
            if ts.get("serverName"):
                params["sni"] = ts["serverName"]
            if ts.get("fingerprint"):
                params["fp"] = ts["fingerprint"]
            if ts.get("alpn"):
                params["alpn"] = ",".join(ts["alpn"])

        elif security == "reality":
            rs = stream.get("realitySettings", {})
            params["sni"] = rs.get("serverName", "")
            params["pbk"] = rs.get("publicKey", "")
            params["sid"] = rs.get("shortId", "")
            if rs.get("fingerprint"):
                params["fp"] = rs["fingerprint"]

        if network == "ws":
            ws = stream.get("wsSettings", {})
            if ws.get("path"):
                params["path"] = ws["path"]
            ws_host = (ws.get("headers") or {}).get("Host")
            if ws_host:
                params["host"] = ws_host

        elif network == "grpc":
            gs = stream.get("grpcSettings", {})
            if gs.get("serviceName"):
                params["serviceName"] = gs["serviceName"]

        query = urllib.parse.urlencode({
            k: v for k, v in params.items() if v not in (None, "")
        })

        frag = urllib.parse.quote(remarks)

        return f"trojan://{password}@{address}:{port}?{query}#{frag}"

    except Exception:
        return None


_VALID_JSON_ESCAPES = set('"\\/bfnrtu')


def _repair_json_escapes(text):
    """Некоторые экспортированные конфиги содержат невалидные с точки
    зрения строгого JSON escape-последовательности — например regexp-
    паттерны вида "regexp:.*\\.ru$" вместо правильного "...\\\\.ru$".
    Чиним по минимуму: одиночный backslash не перед допустимым
    escape-символом удваиваем, не трогая остальной текст."""

    result = []
    i = 0
    n = len(text)

    while i < n:

        ch = text[i]

        if ch == "\\" and i + 1 < n:

            nxt = text[i + 1]

            if nxt in _VALID_JSON_ESCAPES:
                result.append(ch)
                result.append(nxt)
                i += 2
                continue

            result.append("\\\\")
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def extract_all_uris_from_xray_json(chunk):
    """Принимает текст целого Xray/V2Ray клиентского JSON-конфига (или
    просто один outbound-объект) и достаёт из него ВСЕ vless:// / hysteria2://
    ссылки (не только первую) — важно для конфигов с балансировщиком/
    автовыбором между несколькими серверами: один URI физически не может
    нести в себе автовыбор (это настройка клиента, не подписки), поэтому
    единственный честный вариант — отдать всех кандидатов, чтобы наш
    собственный пайплайн (3 раунда тестов + отбор лучших) выбрал сам.
    Правила маршрутизации из такого JSON намеренно игнорируются — подписка
    физически не может их нести."""

    data = None

    try:
        data = json.loads(chunk)
    except Exception:
        try:
            data = json.loads(_repair_json_escapes(chunk))
        except Exception:
            return []

    base_remark = (
        data.get("remarks")
        or data.get("ps")
        or data.get("name")
        or "Imported"
    )

    outbounds = data.get("outbounds")

    if not outbounds and data.get("protocol"):
        # сам объект - это один outbound, а не обёртка целого клиента
        outbounds = [data]

    if not outbounds:
        return []

    results = []

    for ob in outbounds:

        proto = ob.get("protocol")
        uri = None

        if proto == "vless":
            uri = _vless_outbound_to_uri(ob, base_remark)

        elif proto == "hysteria":
            uri = _hysteria_outbound_to_uri(ob, base_remark)

        elif proto == "trojan":
            uri = _trojan_outbound_to_uri(ob, base_remark)

        if not uri:
            continue

        # если кандидатов несколько - различаем remark по tag,
        # иначе все получат одинаковое название
        if len(results) >= 1:
            tag = ob.get("tag", "")
            new_remark = (
                f"{base_remark} {tag}".strip()
                if tag
                else f"{base_remark} #{len(results) + 1}"
            )
            base_part, _ = uri.rsplit("#", 1)
            uri = base_part + "#" + urllib.parse.quote(new_remark)

        results.append(uri)

    return results


def extract_uri_from_xray_json(chunk):
    """Как extract_all_uris_from_xray_json(), но только первый найденный
    сервер — оставлено для обратной совместимости."""
    uris = extract_all_uris_from_xray_json(chunk)
    return uris[0] if uris else None


URI_LINE_PREFIXES = (
    "vless://", "trojan://", "hysteria2://", "hy2://",
    "@", "t.me/", "http://t.me/", "https://t.me/",
)


def load_manual_entries(path):
    """Как load_lines(), но вдобавок понимает вставленный целиком
    Xray/V2Ray JSON-конфиг (в один или несколько физических строк) —
    достаёт из него ссылку на сервер через extract_uri_from_xray_json()."""

    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as f:
        raw_text = f.read()

    entries = []
    json_buffer = []

    def flush_json_buffer():
        if not json_buffer:
            return
        chunk = "\n".join(json_buffer).strip()
        json_buffer.clear()
        if not chunk:
            return
        uris = extract_all_uris_from_xray_json(chunk)
        if uris:
            entries.extend(uris)
            if len(uris) > 1:
                print(
                    f"[i] {path}: из одного JSON-блока извлечено "
                    f"{len(uris)} серверов (авто-подбор/балансировщик)"
                )
        else:
            print(
                f"[!] {path}: не удалось разобрать JSON-блок "
                f"(начало: {chunk[:60]}...)",
                file=sys.stderr
            )

    FILTERED_SCHEMES = ("vmess://", "ss://", "shadowsocks://")

    for line in raw_text.splitlines():

        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            flush_json_buffer()
            continue

        if stripped.startswith(FILTERED_SCHEMES):
            flush_json_buffer()
            continue

        if stripped.startswith(URI_LINE_PREFIXES):
            flush_json_buffer()
            entries.append(stripped)
            continue

        # похоже на часть (много)строчного JSON - копим до конца блока
        json_buffer.append(stripped)

    flush_json_buffer()

    return entries


def parse_uri(uri):
    try:
        scheme = uri.split(
            "://",
            1
        )[0].lower()

        if scheme in ("vless", "trojan"):
            return parse_vless_trojan(
                uri,
                scheme
            )

        if scheme in (
            "hysteria2",
            "hy2"
        ):
            return parse_hysteria2(uri)

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

    manual_uris = load_manual_entries(
        manual_path
    )

    raw_uris = []
    uri_source = {}

    # Сначала реальные источники
    for source in sources:
        fetched = fetch_source(source)
        for uri in fetched:
            raw_uris.append(uri)
            if uri not in uri_source:
                uri_source[uri] = source

    # Manual НЕ получает привилегий.
    # Он просто добавляет конфиги в общий пул.
    for uri in manual_uris:
        raw_uris.append(uri)
        if uri not in uri_source:
            uri_source[uri] = "manual"

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
    skipped_protocol = 0

    ALLOWED_SCHEMES = ("vless://", "hysteria2://", "hy2://")

    for uri in raw_uris:

        if not uri.startswith(ALLOWED_SCHEMES):
            skipped_protocol += 1
            continue

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

        src = uri_source.get(uri, "unknown")
        try:
            meta["source"] = urllib.parse.urlparse(src).netloc or src
        except Exception:
            meta["source"] = src

        meta["is_manual"] = uri in manual_uris
        
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
        f"other protocols filtered out "
        f"(vmess/ss/etc): {skipped_protocol}"
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
# ОТБОР С ЛИМИТОМ НА СТРАНУ
# ==========================================================================

def cap_per_country(
    results,
    max_output,
    max_per_country
):
    """results уже отсортированы по качеству (лучшие первые).
    Берёт лучшие, но не больше max_per_country от одной страны,
    пока не наберёт max_output штук."""

    selected = []

    country_counts = {}

    for result in results:

        code = result.get(
            "country_code",
            "UN"
        )

        if country_counts.get(
            code,
            0
        ) >= max_per_country:
            continue

        selected.append(result)

        country_counts[code] = (
            country_counts.get(code, 0)
            + 1
        )

        if len(selected) >= max_output:
            break

    return selected


# ==========================================================================
# ИСТОРИЯ НАДЁЖНОСТИ (между запусками)
# ==========================================================================

HISTORY_MIN_SAMPLES = 3
HISTORY_MIN_PASS_RATE = 0.5
HISTORY_MAX_AGE_DAYS = 30


def _history_key(proto, host, port):
    return f"{proto}|{host}|{port}"


def load_history(path):
    if not os.path.exists(path):
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(path, history):

    now = datetime.datetime.now(
        datetime.timezone.utc
    )

    cutoff = now - datetime.timedelta(
        days=HISTORY_MAX_AGE_DAYS
    )

    pruned = {}

    for key, entry in history.items():
        try:
            last_run = datetime.datetime.fromisoformat(
                entry.get("last_run", "")
            )
        except Exception:
            continue

        if last_run >= cutoff:
            pruned[key] = entry

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            pruned,
            f,
            ensure_ascii=False,
            indent=2
        )


def apply_history(final_ok, history):
    """Убирает конфиги, которые исторически часто отваливались, даже если
    сейчас случайно прошли 3 раунда. Остальным поднимает/опускает
    quality_score по историческому проценту успеха."""

    result = []

    for item in final_ok:

        key = _history_key(
            item["proto"],
            item["host"],
            item["port"]
        )

        hist = history.get(
            key,
            {"seen": 0, "passed": 0}
        )

        seen = hist.get("seen", 0)
        passed = hist.get("passed", 0)

        if seen >= HISTORY_MIN_SAMPLES:

            rate = passed / seen

            if rate < HISTORY_MIN_PASS_RATE:
                # исторически ненадёжный — не пускаем, даже если сейчас повезло
                continue

            item["quality_score"] = round(
                item["quality_score"]
                * (0.7 + 0.3 * rate),
                2
            )

            item["history_pass_rate"] = round(rate, 2)

        result.append(item)

    return result


def update_history(history, tested_keys, passed_keys):

    now_iso = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()

    for key in tested_keys:

        hkey = _history_key(*key)

        entry = history.get(
            hkey,
            {"seen": 0, "passed": 0}
        )

        entry["seen"] = entry.get("seen", 0) + 1

        if key in passed_keys:
            entry["passed"] = entry.get("passed", 0) + 1

        entry["last_run"] = now_iso

        history[hkey] = entry

    return history


# ==========================================================================
# СРОК ДЕЙСТВИЯ ПОДПИСКИ
# ==========================================================================
# Формат expiry.txt (по одной строке на категорию):
#   normal: 2026-12-31
#   white: never
# "never" или отсутствие строки = без ограничения срока.
#
# ВАЖНО (честно): это не настоящая серверная авторизация — сами VPN-сервера
# в источниках ничего не знают про эту дату и продолжат принимать любого,
# кто как-то узнает их адрес напрямую. Что эта система РЕАЛЬНО даёт:
# как только дата истекла, наш скрипт перестаёт публиковать рабочие
# конфиги в файле подписки — при следующем обновлении подписки в клиенте
# (по расписанию раз в N часов, или вручную) список станет пустым.
# Мгновенного отключения "здесь и сейчас" у уже подключённого человека
# это не даёт — только у бесплатных платных VPN с полноценным сервером
# авторизации это возможно, а не у статического файла на GitHub.

def load_expiry(path):

    result = {
        "normal": None,
        "white": None,
        "manual": None,
    }

    if not os.path.exists(path):
        return result

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip().lower()

            if key not in result:
                continue

            if value in ("", "never", "нет", "никогда"):
                result[key] = None
                continue

            try:
                result[key] = datetime.datetime.strptime(
                    value,
                    "%Y-%m-%d"
                ).replace(
                    tzinfo=datetime.timezone.utc
                )
            except ValueError:
                print(
                    f"[!] expiry.txt: не понял дату "
                    f"'{value}' для '{key}', "
                    f"формат ГГГГ-ММ-ДД или never"
                )
                result[key] = None

    return result


def expiry_status(category, expiry_map):
    """Возвращает (is_expired, unix_timestamp_или_0, дней_осталось_или_None)."""

    expires_at = expiry_map.get(category)

    if expires_at is None:
        return False, 0, None

    now = datetime.datetime.now(
        datetime.timezone.utc
    )

    is_expired = now >= expires_at

    days_left = (expires_at - now).days

    return is_expired, int(expires_at.timestamp()), days_left


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

    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Пропустить тесты Xray"
    )

    parser.add_argument(
    "--manual-fast",
    action="store_true",
    help="Не тестировать конфиги из manual.txt и manual_whitelist.txt"
)

    parser.add_argument(
        "--max-per-country",
        type=int,
        default=2,
        help="Максимум конфигов от одной страны в каждой подписке"
    )

    parser.add_argument(
        "--repo-raw-base",
        type=str,
        default="",
        help="Базовый raw.githubusercontent.com URL репозитория "
             "(для генерации QR-кода на подписку), например: "
             "https://raw.githubusercontent.com/ник/репо/main"
    )

    parser.add_argument(
        "--expiry-file",
        type=str,
        default="expiry.txt",
        help="Файл со сроком действия подписок по категориям"
    )

    args = parser.parse_args()

    expiry_map = load_expiry(
        args.expiry_file
    )

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
    
    # ------------------------------------------------------------------
    # LOAD
    # ------------------------------------------------------------------

    if args.skip_test:
        print(
            "[i] ⚡ --skip-test: "
            "быстрый ручной режим"
        )

        normal_items = load_category(
            "",
            args.manual,
            "normal",
            blacklist
        )

        white_items = load_category(
            "",
            args.manual_white,
            "white",
            blacklist
        )

    else:
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
    final_ok = []
    round1 = []
    round2 = []
    round3 = []

    # ==============================================================
    # ПОЛНОСТЬЮ ОТКЛЮЧИТЬ ТЕСТЫ
    # ==============================================================
    if args.skip_test:

        print(
            "[i] ⚡ --skip-test: "
            "пропускаю тестирование ВСЕХ конфигов..."
        )

        for meta, outbound in all_items:
            final_ok.append({
                **meta,
                "ok": True,
                "error": None,
                "latency_ms": 0,
                "speed_kbps": 0,
                "quality_score": 0.0,
            })

    else:
        # ==========================================================
        # MANUAL FAST
        # ==========================================================

        manual_items = []
        test_items = []

        for meta, outbound in all_items:

            if (
                args.manual_fast
                and meta.get(
                    "is_manual",
                    False
                )
            ):
                manual_items.append(
                    (
                        meta,
                        outbound
                    )
                )
            else:
                test_items.append(
                    (
                        meta,
                        outbound
                    )
                )

        if manual_items:

            print(
                f"[i] ⚡ Manual fast: "
                f"{len(manual_items)} ручных конфигов "
                f"без тестирования."
            )

            for meta, outbound in manual_items:

                final_ok.append({
                    **meta,
                    "ok": True,
                    "error": None,

                    # Нулевые значения здесь специально.
                    # Ручные конфиги не проходят тест.
                    "latency_ms": None,
                    "speed_kbps": None,

                    # Чтобы ручные конфиги не проигрывали
                    # автоматически протестированным.
                    "quality_score": 0.0,
                })

        # ==========================================================
        # АВТОМАТИЧЕСКИЕ КОНФИГИ
        # ==========================================================

        if test_items:

            print(
                f"[i] Раунд 1: "
                f"проверяю "
                f"{len(test_items)} конфигов..."
            )

            round1 = run_round(
                args.xray_bin,
                test_items,
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
                f"{len(test_items)}"
            )

            survivors = [
                (
                    meta,
                    outbound
                )

                for meta, outbound
                in test_items

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

            # ======================================================
            # ROUND 2
            # ======================================================

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

            def passes_thresholds(result):

                if not result.get(
                    "ok",
                    False
                ):
                    return False

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
                    return False

                is_bypass = result.get(
                    "is_bypass",
                    False
                )

                if is_bypass:
                    max_latency = args.bypass_max_latency_ms
                    min_speed = args.bypass_min_speed_kbps
                else:
                    max_latency = args.max_latency_ms
                    min_speed = args.min_speed_kbps

                return (
                    latency <= max_latency
                    and speed >= min_speed
                )

            round2_by_key = {
                (r["proto"], r["host"], r["port"]): r
                for r in round2
            }

            round2_ok_keys = {
                key
                for key, r in round2_by_key.items()
                if passes_thresholds(r)
            }

            print(
                f"[i] Раунд 2: прошли "
                f"{len(round2_ok_keys)}/{len(survivors)}"
            )

            round2_survivors = [
                (meta, outbound)
                for meta, outbound in survivors
                if (meta["proto"], meta["host"], meta["port"]) in round2_ok_keys
            ]

            # ======================================================
            # ПАУЗА ПЕРЕД РАУНДОМ 3 — та же логика, что и перед
            # раундом 2: конфиг должен продержаться ещё какое-то
            # время, а не просто ответить один раз и отвалиться.
            # ======================================================

            if (
                round2_survivors
                and args.round_gap > 0
            ):
                print(
                    f"[i] Жду ещё "
                    f"{args.round_gap:.0f} сек перед раундом 3..."
                )

                time.sleep(
                    args.round_gap
                )

            # ======================================================
            # ROUND 3 — независимое повторное подтверждение
            # ======================================================

            print(
                f"[i] Раунд 3 (подтверждение стабильности): "
                f"{len(round2_survivors)} конфигов..."
            )

            round3 = run_round(
                args.xray_bin,
                round2_survivors,
                args.workers,
                args.timeout,
                args.speed_timeout,
                True
            )

            round3_by_key = {
                (r["proto"], r["host"], r["port"]): r
                for r in round3
            }

            round3_ok = 0

            # ======================================================
            # FINAL FILTER — должен пройти И раунд 2, И раунд 3.
            # Итоговые цифры — худшие (консервативные) из двух
            # раундов, чтобы не засчитывать случайный всплеск.
            # ======================================================

            for key in round2_ok_keys:

                r3 = round3_by_key.get(key)

                if not r3 or not passes_thresholds(r3):
                    continue

                round3_ok += 1

                r2 = round2_by_key[key]

                combined_latency = max(
                    r2["latency_ms"],
                    r3["latency_ms"]
                )

                combined_speed = min(
                    r2["speed_kbps"],
                    r3["speed_kbps"]
                )

                result = {
                    **r3,
                    "latency_ms": combined_latency,
                    "speed_kbps": combined_speed,
                }

                result["quality_score"] = (
                    calculate_score(
                        combined_speed,
                        combined_latency
                    )
                )

                final_ok.append(
                    result
                )

            print(
                f"[i] Раунд 3: подтвердили "
                f"{round3_ok}/{len(round2_survivors)}"
            )

        else:

            # Переменные нужны report.json
            round1 = []
            round2 = []
            round3 = []

    # ------------------------------------------------------------------
    # ИСТОРИЯ НАДЁЖНОСТИ
    # ------------------------------------------------------------------
    # Работает только когда реально было тестирование (round2/round3
    # непусты) — в --skip-test историю не трогаем, там сигнала нет.

    history_path = os.path.join(
        args.outdir,
        "history.json"
    )

    history = load_history(history_path)

    tested_keys = {
        (r["proto"], r["host"], r["port"])
        for r in (round2 + round3)
    }

    passed_keys = {
        (r["proto"], r["host"], r["port"])
        for r in final_ok
    }

    if tested_keys:

        final_ok = apply_history(
            final_ok,
            history
        )

        history = update_history(
            history,
            tested_keys,
            passed_keys
        )

        save_history(
            history_path,
            history
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

        "round3": round3,

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

    status_summary = {}

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

            selected = cap_per_country(
                selected,
                args.max_output,
                args.max_per_country
            )

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

            bypass = cap_per_country(
                bypass,
                args.bypass_output,
                args.max_per_country
            )

            regular_slots = max(
                0,
                args.max_output
                - len(bypass)
            )

            regular = cap_per_country(
                regular,
                regular_slots,
                args.max_per_country
            )

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
        # СРОК ДЕЙСТВИЯ
        # --------------------------------------------------------------

        is_expired, expire_ts, days_left = expiry_status(
            category,
            expiry_map
        )

        if is_expired:
            # Истёкшая подписка публикуется НАМЕРЕННО пустой — это не
            # авария теста, поэтому ниже разрешаем перезаписать файл
            # даже при пустом final_lines.
            selected = []

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

        def _b64(text):
            return base64.b64encode(
                text.encode("utf-8")
            ).decode("utf-8")

        if category == "white":

            profile_title = "🐇 Tuskone | БС"

            announce_text = (
                "Эти конфиги — для обхода блокировок мобильного "
                "интернета (белые списки). Используйте их только "
                "при таких блокировках."
            )

        else:

            profile_title = "🐇 Tuskone VPN"

            announce_text = (
                "Обычные конфиги для повседневного использования. "
                "Пожалуйста, не скачивайте торренты через VPN."
            )

        if is_expired:

            profile_title = profile_title + " (истекла)"

            announce_text = (
                "Срок действия этой подписки истёк. "
                "Обратитесь к администратору для продления."
            )

        elif days_left is not None and days_left <= 3:

            announce_text = (
                announce_text
                + f" ⚠️ Осталось дней: {days_left}."
            )

        # Заголовки подписки (метаданные для клиентов, формат INCY/Happ)
        headers = [
            f"#profile-title: base64:{_b64(profile_title)}",
            "#profile-update-interval: 6",
            f"#announce: base64:{_b64(announce_text)}",
            f"#subscription-userinfo: upload=0; download=0; "
            f"total=0; expire={expire_ts}",
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

        qr_path = os.path.join(
            args.outdir,
            f"qr{suffix}.png"
        )

        if not final_lines and not is_expired:

            # Ничего рабочего в этом прогоне — НЕ затираем прошлый
            # рабочий файл (он уже лежит в output/ после checkout).
            # Просто громко предупреждаем в логе.
            print(
                f"[!!!] [{category}] ВНИМАНИЕ: 0 рабочих конфигов "
                f"в этом прогоне — файл {sub_path} оставлен БЕЗ "
                f"ИЗМЕНЕНИЙ (сохранена предыдущая рабочая версия)."
            )

        elif is_expired:

            # Осознанное опустошение по сроку действия — это НЕ авария,
            # публикуем поверх прошлой версии.
            print(
                f"[i] [{category}] Срок действия истёк — "
                f"публикую подписку без конфигов."
            )

            with open(
                sub_path,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(
                    sub_b64
                )

        else:

            with open(
                sub_path,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(
                    sub_b64
                )

            try:
                import qrcode

                sub_url = (
                    f"{args.repo_raw_base}/output/"
                    f"subscription{suffix}.txt"
                    if args.repo_raw_base
                    else None
                )

                if sub_url:
                    img = qrcode.make(sub_url)
                    img.save(qr_path)

            except Exception as e:
                print(
                    f"[!] [{category}] "
                    f"QR-код не сгенерирован: {e}"
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

        source_counts = {}

        for result in selected:

            src = result.get(
                "source",
                "unknown"
            )

            source_counts[src] = (
                source_counts.get(src, 0)
                + 1
            )

        print(
            f"[i] [{category}] "
            f"Источники (сколько рабочих дал каждый):"
        )

        for src, count in sorted(
            source_counts.items(),
            key=lambda x: (-x[1], x[0])
        ):
            print(
                f"    {src}: {count}"
            )

        print(
            "=================================================="
        )
        print("")

        status_summary[category] = {
            "count": len(final_lines),
            "empty_this_run": not final_lines,
            "countries": countries,
            "sources": source_counts,
        }

    # ------------------------------------------------------------------
    # ОТДЕЛЬНЫЙ "РУЧНОЙ" ФАЙЛ — только manual.txt + manual_whitelist.txt,
    # без автотеста и без источников. Нужен для персональной раздачи
    # через Cloudflare Worker (см. отдельную инструкцию) — там срок
    # действия задаётся индивидуально на человека, а не на весь файл.
    # ------------------------------------------------------------------

    manual_raw = (
        load_manual_entries(args.manual)
        + load_manual_entries(args.manual_white)
    )

    manual_seen = set()
    manual_lines = []

    manual_is_expired, _, _ = expiry_status(
        "manual",
        expiry_map
    )

    if manual_is_expired:

        print(
            "[i] [manual] Срок действия истёк "
            "(expiry.txt: manual) — публикую пустой файл. "
            "Это общий рубильник для ВСЕХ персональных ссылок "
            "через Cloudflare Worker разом."
        )

    else:

        for uri in manual_raw:

            result = parse_uri(uri)

            if not result:
                continue

            meta, _ = result

            if any(b in meta["host"] for b in blacklist):
                continue

            key = (meta["proto"], meta["host"], meta["port"])

            if key in manual_seen:
                continue

            manual_seen.add(key)
            manual_lines.append(uri)

    if manual_lines or manual_is_expired:

        def _b64_manual(text):
            return base64.b64encode(
                text.encode("utf-8")
            ).decode("utf-8")

        if manual_is_expired:

            manual_title = "🐇 Tuskone VPN (истекла)"

            manual_announce = (
                "Срок действия этой подписки истёк. "
                "Обратитесь к администратору для продления."
            )

        else:

            manual_title = "🐇 Tuskone VPN"

            manual_announce = (
                "Используйте конфиг обхода только при блокировках "
                "мобильной сети. Пожалуйста, не скачивайте торренты "
                "через VPN."
            )

        _, manual_expire_ts, _ = expiry_status(
            "manual",
            expiry_map
        )

        manual_headers = [
            f"#profile-title: base64:{_b64_manual(manual_title)}",
            "#profile-update-interval: 12",
            f"#announce: base64:{_b64_manual(manual_announce)}",
            f"#subscription-userinfo: upload=0; download=0; "
            f"total=0; expire={manual_expire_ts}",
        ]

        manual_content = manual_headers + manual_lines

        manual_b64 = base64.b64encode(
            "\n".join(manual_content).encode("utf-8")
        ).decode("utf-8")

        manual_path = os.path.join(
            args.outdir,
            "subscription_manual.txt"
        )

        with open(
            manual_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(manual_b64)

        print(
            f"[i] [manual] отдельный файл для Cloudflare Worker: "
            f"{len(manual_lines)} конфигов -> {manual_path}"
        )

    else:

        print(
            "[!!!] [manual] ВНИМАНИЕ: 0 конфигов в manual.txt/"
            "manual_whitelist.txt — файл subscription_manual.txt "
            "оставлен БЕЗ ИЗМЕНЕНИЙ."
        )

    # ------------------------------------------------------------------
    # STATUS.md — сводка на самом видном месте, без лазания по логам
    # ------------------------------------------------------------------

    now_str = datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Статус подписок",
        "",
        f"Последний запуск: {now_str}",
        "",
    ]

    labels = {
        "normal": "🐇 Обычная подписка",
        "white": "🐇 Белые списки (БС)",
    }

    for category in ("normal", "white"):

        info = status_summary.get(
            category,
            {"count": 0, "empty_this_run": True,
             "countries": {}, "sources": {}}
        )

        lines.append(f"## {labels[category]}")
        lines.append("")

        if info["empty_this_run"]:
            lines.append(
                "⚠️ **В этом прогоне рабочих конфигов не найдено — "
                "показана предыдущая опубликованная версия.**"
            )
        else:
            lines.append(
                f"✅ Рабочих конфигов: **{info['count']}**"
            )

        lines.append("")

        if info["countries"]:
            lines.append("Страны:")
            for country, count in sorted(
                info["countries"].items(),
                key=lambda x: (-x[1], x[0])
            ):
                lines.append(f"- {country}: {count}")
            lines.append("")

    status_path = os.path.join(
        args.outdir,
        "STATUS.md"
    )

    with open(
        status_path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "\n".join(lines)
        )


if __name__ == "__main__":
    main()
