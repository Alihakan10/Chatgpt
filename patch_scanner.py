from pathlib import Path
import subprocess
import sys
import textwrap

PATH = Path("scanner.py")
MARKER = "# SAFE_TELEGRAM_STATE_PATCH_V1"


def main():
    if not PATH.exists():
        raise RuntimeError("scanner.py bulunamadi.")

    source = PATH.read_text(encoding="utf-8")

    if MARKER in source:
        print("OK: scanner.py yamasi zaten uygulanmis.")
        return

    start = source.find("def send_telegram(message):")
    end = source.find(
        "# ============================================================\n# FIYAT FORMAT",
        start,
    )

    if start < 0 or end < 0:
        raise RuntimeError(
            "send_telegram() bolumu bulunamadi; dosya degistirilmedi."
        )

    telegram_function = textwrap.dedent(
        '''
        # SAFE_TELEGRAM_STATE_PATCH_V1
        TELEGRAM_RETRY_DELAYS = (2, 5, 10)


        def send_telegram(message):

            if not TELEGRAM_BOT_TOKEN:
                raise RuntimeError(
                    "TELEGRAM_BOT_TOKEN bulunamadi."
                )

            if not TELEGRAM_CHAT_ID:
                raise RuntimeError(
                    "TELEGRAM_CHAT_ID bulunamadi."
                )

            url = (
                "https://api.telegram.org/bot"
                + TELEGRAM_BOT_TOKEN
                + "/sendMessage"
            )

            max_length = 3900
            chunks = []
            current = ""

            for line in message.splitlines(keepends=True):

                if len(current) + len(line) > max_length:

                    if current:
                        chunks.append(current)

                    current = line

                else:
                    current += line

            if current:
                chunks.append(current)

            if not chunks:
                chunks = [""]

            for chunk_no, chunk in enumerate(chunks, 1):

                payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True
                }

                last_error = None

                for attempt in range(len(TELEGRAM_RETRY_DELAYS) + 1):

                    try:

                        response = requests.post(
                            url,
                            json=payload,
                            timeout=REQUEST_TIMEOUT
                        )

                        if response.ok:

                            try:
                                result = response.json()
                            except Exception as exc:
                                last_error = RuntimeError(
                                    "Telegram JSON cevabi okunamadi: "
                                    + str(exc)
                                )
                            else:
                                if result.get("ok"):
                                    last_error = None
                                    break

                                last_error = RuntimeError(
                                    "Telegram hatasi: "
                                    + str(result)
                                )

                        else:

                            try:
                                detail = response.json()
                            except Exception:
                                detail = response.text

                            last_error = RuntimeError(
                                "Telegram HTTP "
                                + str(response.status_code)
                                + ": "
                                + str(detail)
                            )

                            if response.status_code not in (
                                429, 500, 502, 503, 504
                            ):
                                raise last_error

                    except requests.RequestException as exc:
                        last_error = exc

                    if attempt < len(TELEGRAM_RETRY_DELAYS):

                        delay = TELEGRAM_RETRY_DELAYS[attempt]

                        log(
                            "Telegram chunk "
                            + str(chunk_no)
                            + "/"
                            + str(len(chunks))
                            + " basarisiz; "
                            + str(delay)
                            + " saniye sonra tekrar denenecek."
                        )

                        time.sleep(delay)

                if last_error is not None:

                    raise RuntimeError(
                        "Telegram gonderilemedi (chunk "
                        + str(chunk_no)
                        + "/"
                        + str(len(chunks))
                        + "): "
                        + str(last_error)
                    )

                if chunk_no < len(chunks):
                    time.sleep(0.3)
        '''
    )

    source = source[:start] + telegram_function + "\n\n" + source[end:]

    old_order = """    save_state(
        state
    )

    # --------------------------------------------------------
    # YENI AL YOK
    # --------------------------------------------------------

    if not new_buy_results:

        log(
            "Son taramada yeni "
            "SAT -> AL donusu bulunamadi."
        )

        log(
            "Telegram mesaji GONDERILMEYECEK."
        )

        log(
            "PROGRAM BASARIYLA TAMAMLANDI."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = build_telegram_message(
        new_buy_results
    )

    send_telegram(
        message
    )

    log(
        "Telegram bildirimi basariyla gonderildi."
    )

    log(
        "PROGRAM BASARIYLA TAMAMLANDI."
    )
"""

    new_order = """    # --------------------------------------------------------
    # YENI AL YOK
    # --------------------------------------------------------

    if not new_buy_results:

        save_state(
            state
        )

        log(
            "Son taramada yeni "
            "SAT -> AL donusu bulunamadi."
        )

        log(
            "Telegram mesaji GONDERILMEYECEK."
        )

        log(
            "PROGRAM BASARIYLA TAMAMLANDI."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    # Yeni AL varsa once Telegram basarili olmali.
    # Telegram basarisiz olursa save_state calismaz.
    # Boylece sonraki taramada sinyal yeniden yakalanabilir.

    message = build_telegram_message(
        new_buy_results
    )

    send_telegram(
        message
    )

    # Telegram basarili olduktan sonra state kaydedilir.
    save_state(
        state
    )

    log(
        "Telegram bildirimi basariyla gonderildi."
    )

    log(
        "PROGRAM BASARIYLA TAMAMLANDI."
    )
"""

    if old_order not in source:
        raise RuntimeError(
            "main state/Telegram siralamasi bulunamadi; dosya degistirilmedi."
        )

    source = source.replace(old_order, new_order, 1)
    PATH.write_text(source, encoding="utf-8")

    check = subprocess.run(
        [sys.executable, "-m", "py_compile", "scanner.py"],
        capture_output=True,
        text=True,
    )

    if check.returncode != 0:
        print(check.stdout)
        print(check.stderr)
        raise RuntimeError(
            "scanner.py syntax kontrolu basarisiz; commit yapilmadi."
        )

    subprocess.run(
        ["git", "config", "user.name", "github-actions[bot]"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        check=True,
    )
    subprocess.run(["git", "add", "scanner.py"], check=True)

    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        check=False,
    )

    if changed.returncode != 0:
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Fix Telegram retry and state save order",
            ],
            check=True,
        )
        subprocess.run(["git", "push"], check=True)
        print("OK: scanner.py yamasi commit edilip push edildi.")
    else:
        print("OK: scanner.py icin yeni degisiklik yok.")


if __name__ == "__main__":
    main()
