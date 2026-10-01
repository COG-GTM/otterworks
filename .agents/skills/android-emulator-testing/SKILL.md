---
name: android-emulator-testing
description: How to drive and verify the OtterWorks Capacitor Android app on the `otter` emulator - signing in, uploading files, reading Android notifications, recording usable video, and working around emulator quirks. Use when testing any client-app change that must be validated on Android rather than the web build.
---

# Testing the OtterWorks Android app on the `otter` emulator

`.devin/blueprint.yaml` already installs the SDK, creates the `otter` AVD (720x1600, density 320),
warms a `clean` snapshot, and seeds the RetailCo drive. This skill covers the *runtime* mechanics the
blueprint does not.

## Bring-up

```bash
export PATH=$HOME/Android/Sdk/platform-tools:$HOME/Android/Sdk/emulator:$PATH
sudo chmod 666 /dev/kvm                     # perms reset each boot
DISPLAY=:0 emulator -avd otter -no-audio -gpu swiftshader_indirect \
  -snapshot clean -no-snapshot-save &
adb wait-for-device
# Backend: `make dev-backend` (gateway :8080; the app hits http://10.0.2.2:8080/api/v1)
```

Rebuild/redeploy the app:

```bash
. ~/.nvm/nvm.sh && nvm use default
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
cd frontend/client-app && npm run build && npx cap sync android \
  && npx cap run android --target emulator-5554 --no-sync
```

`make dev-android`'s final `npx cap run android` prompts for a target and aborts without a TTY —
**always pass `--target emulator-5554`**.

## Recording-friendly window setup

The emulator window is portrait 720x1600 and will not fit a 1024x768-scaled desktop at full size.
Size it to the full screen height *before* starting the recording:

```bash
wmctrl -l                                     # find "Android Emulator - otter:5554"
wmctrl -r "Android Emulator - otter:5554" -e 0,320,0,340,745
wmctrl -c "Home — Dolphin"                    # close stray windows that clutter the frame
```

Then capture evidence with `zoom` on the emulator region rather than full-screen screenshots — the
phone UI is unreadable otherwise. Mapping from screenshot coords to emulator coords with the window
above is roughly `emu = (screenshot - origin) * 3.38`; when in doubt, `adb exec-out screencap -p >
/tmp/s.png` gives you a native 720x1600 image whose pixel coords are directly usable with
`adb shell input tap`.

## Signing in

The app starts on the marketing landing page. Credentials are the `DRIVE_EMAIL` / `DRIVE_PASSWORD`
secrets (same account that owns the seeded drive).

**First check the account actually exists.** If the Postgres volume was recreated (`make infra-up`
after a `down -v`, a fresh box, etc.) the seeded drive account is gone and every sign-in — app *and*
API — returns `Invalid credentials`, which looks like a typing/IME bug but is not:

```bash
docker exec otterworks-postgres psql -U otterworks -d otterworks -c 'select email from users;'
# only admin@otterworks.dev  ->  re-seed before testing
python3 -m venv /tmp/retail-seed-venv
/tmp/retail-seed-venv/bin/pip install -q -r testdata/generated/retail-drive/requirements.txt
/tmp/retail-seed-venv/bin/python testdata/generated/retail-drive/generate_drive.py \
  --gateway http://localhost:8080 --email "$DRIVE_EMAIL" --password "$DRIVE_PASSWORD" \
  --departments all --scale 0.1 --workers 6 --no-docs --register
```

`--scale 0.1 --no-docs` seeds all 15 departments with 107 files in well under a minute (vs. 2,172 at
`--scale 1.0`) and is plenty for UI testing. `--register` creates the account. Check the exact counts
for any scale with `generate_drive.py --dry-run` (it still needs `--gateway/--email/--password`);
a real run also uploads the 3 committed media clips in `assets/`, which the dry-run total omits.

Quick credential check without the UI:
`curl -s -X POST http://localhost:8080/api/v1/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"$DRIVE_EMAIL\",\"password\":\"$DRIVE_PASSWORD\"}"`

```bash
adb shell input tap 215 880          # "Sign In" on landing page
adb shell input tap 359 739; adb shell input text "$DRIVE_EMAIL"
adb shell input tap 359 915; adb shell input text "$DRIVE_PASSWORD"
adb shell input keyevent 4           # hide the IME (it covers the submit button)
adb shell input tap 359 1037         # "Sign in"
```

Gotchas:
- **Do not** use `keyevent 111` (ESC) to dismiss the keyboard — it can insert a character into the
  focused field. Use `keyevent 4` (Back).
- `am force-stop com.otterworks.app` + relaunch **loses the session** and returns you to the landing
  page. Avoid restarting the app just to refresh data; navigate away and back instead.
- The hardware **Back key exits the activity** from a folder view (it does not navigate up within the
  SPA), and relaunching also lands on the signed-out landing page. Budget for a re-login, or navigate
  with in-app breadcrumbs / the nav drawer instead of Back. Re-login mid-test is disruptive to a
  recording, so avoid Back entirely once recording has started.
- After sign-in the nav drawer is open; dismiss it by tapping the scrim (e.g. `adb shell input tap
  650 900`). The header/hamburger sits *under* the status bar (y < ~50 px), so taps there hit the
  status bar instead of the web view.
- The tap coordinates above assume the pristine form. **A failed sign-in inserts a red error banner
  and pushes the form down**, so the old "Sign in" y no longer hits the button (it re-focuses the
  password field and reopens the IME). After any failed attempt: `keyevent 4` to hide the IME, then
  tap the button at its *current* position (~`360 1121` with the banner shown). Re-screenshot instead
  of reusing coordinates across layout changes.
- Tapping the hamburger is unreliable (status-bar overlap). A reliable way into the Files page from
  the dashboard is the **"View all"** link at the right of the *Recent files* section
  (~`adb shell input tap 622 1521` on a freshly loaded dashboard).

## The "Try out your stylus" popup

Tapping a text input in the web view can raise a system stylus-handwriting tooltip that swallows
input. Disable it once per boot:

```bash
adb shell settings put secure stylus_handwriting_enabled 0
adb shell settings put secure stylus_handwriting_default_value 0
```

## Uploading a file

`Files page → "Upload" button → tap the dropzone → Android Documents UI picker`. Stage files with
`adb push local /sdcard/Download/name.txt`, then make them visible in the picker's "Recent" list:

```bash
adb push /tmp/report-q3.txt /sdcard/Download/report-q3.txt
adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
  -d file:///sdcard/Download/report-q3.txt
```

Without the media-scanner broadcast a freshly pushed file may not appear in the picker.

**Upload into a folder, not the drive root.** At the root the client requests
`GET /files?page=1&page_size=50` with no `folder_id`, and the backend returns an unordered page 1 of
*all* seeded files (2,175 at `--scale 1.0`), so a newly uploaded file is usually invisible there (and
root uploads are stored with no `folder_id` at all). Navigating into a folder that is empty makes the
uploaded file appear immediately and gives unambiguous evidence. Every department has files at both
seed scales, so pick the folder the UI actually shows as empty rather than assuming a particular one;
files sit in nested subfolders, so an empty-looking subfolder is what you want and `--dry-run` (which
only prints per-department totals) will not find it for you.
This may still be broken/unchanged in future runs — the folder workaround is the reliable path.

The in-app success state ("Upload complete — closing shortly" + green check) **auto-dismisses after
3 seconds**, so screenshot it immediately after the upload resolves.

## Verifying Android notifications

```bash
adb shell cmd notification list                      # one row per posted notification
adb shell dumpsys notification --noredact \
  | grep -E "pkg=com.otterworks.app|android.title=|android.text="
adb shell dumpsys package com.otterworks.app | grep POST_NOTIFICATIONS:   # granted=true/false
```

For pixel evidence (required — dumpsys is not proof a user saw it) pull the shade with a real
gesture so the recording looks natural:

```bash
adb shell input swipe 360 2 360 1200 600     # open shade (see note)
adb shell cmd statusbar collapse             # close shade
```

A short/fast swipe (`360 5 360 1000 400`) often fails to latch the shade and leaves you on the app
screen — always screenshot to confirm the shade is really open before asserting on its contents. The
longer, slower `360 2 360 1200 600` gesture is reliable.

To make an "no notification was posted" assertion unambiguous, clear the shade first (open it and tap
**Clear all**, ~`adb shell input tap 568 1132`) and re-check `cmd notification list` shows no
`com.otterworks.app` row before performing the action.

Runtime permission prompts are one-shot per install: check `POST_NOTIFICATIONS: granted=false`
*before* you start recording, otherwise you will never capture the prompt. Reset with
`adb shell pm revoke com.otterworks.app android.permission.POST_NOTIFICATIONS`.

## Forcing a failed network request

To prove a negative (e.g. "no notification on failure"):

```bash
adb shell cmd connectivity airplane-mode enable
# ... perform the action, expect the in-app error state ...
adb shell cmd connectivity airplane-mode disable
```

The web view stays loaded, so the SPA still renders and only the XHR fails — ideal for exercising
error branches. Re-enabling connectivity plus the dropzone's retry (↺) button exercises the
recovery path without re-picking the file.

## Keeping a request in flight (to test cancel / abort paths)

**Emulator network shaping does NOT throttle traffic to the host (`10.0.2.2`).** The emulator console
happily accepts `network speed umts` and `network status` will report `384000 bits/s`, but QEMU's
slirp special-cases the host loopback address, so uploads to the local gateway still complete at
full speed. Do not rely on it.

What works instead: **use a genuinely large file.** Stage one just under the app's 100 MB limit and
you get tens of seconds of in-flight time — plenty to screenshot a partial progress percentage and
click the cancel (X) button.

```bash
head -c 70000000 /dev/urandom | base64 > /tmp/huge-upload.txt   # ~94 MB
adb push /tmp/huge-upload.txt /sdcard/Download/huge-upload.txt
adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
  -d file:///sdcard/Download/huge-upload.txt
```

Always prove the request really was in flight (screenshot showing a progress % strictly between 0
and 100) before asserting anything about the cancel behaviour — otherwise you may be asserting on an
upload that already finished.

For reference, the emulator console needs an auth token:

```python
# python3 - "network speed full"
import socket, os, sys, time
tok = open(os.path.expanduser("~/.emulator_console_auth_token")).read().strip()
s = socket.create_connection(("127.0.0.1", 5554), 10); s.settimeout(5)
time.sleep(0.5); s.recv(65535)
s.sendall(("auth %s\n" % tok).encode()); time.sleep(0.5); s.recv(65535)
for cmd in sys.argv[1:]:
    s.sendall((cmd + "\n").encode()); time.sleep(0.5); print(s.recv(65535).decode())
```

## Debugging notifications that never appear

A notification can be scheduled successfully by JS and still be silently dropped by Android. The two
lines that tell you exactly what happened are in logcat (clear the buffer with `adb logcat -c` right
before the action):

```bash
adb logcat -d | grep -E "LocalNotifications, methodName: schedule|No Channel found"
```

- `V Capacitor: ... pluginId: LocalNotifications, methodName: schedule, methodData: {...}` — proves
  the web layer asked for the notification and shows the exact payload (including `channelId`).
- `E NotificationService: No Channel found for pkg=com.otterworks.app, channelId=<id>, ...` — Android
  discarded it because that channel was never created.

Any `channelId` passed to `LocalNotifications.schedule` **must** first be created with
`LocalNotifications.createChannel`; otherwise the post is dropped with no exception, so an app-side
`try/catch` around `schedule` will never see it. Grep the client for `createChannel` before trusting
any channel-specific notification path. Notifications scheduled with **no** `channelId` fall back to
the plugin's auto-created `default` channel and always work — so "some notifications appear, others
never do" is a strong hint of a missing channel rather than a permission problem.

## Cross-checking against the backend

```bash
docker logs --tail=200 otterworks-file-service 2>&1 | grep "File uploaded"
docker exec otterworks-localstack awslocal dynamodb scan \
  --table-name otterworks-file-metadata --filter-expression "contains(#n, :v)" \
  --expression-attribute-names '{"#n":"name"}' --expression-attribute-values '{":v":{"S":"report"}}'
```

File metadata lives in **LocalStack DynamoDB** (`otterworks-file-metadata`, `otterworks-folders`),
not Postgres — `psql ... -c "select * from files"` will fail. The Postgres role is `otterworks`, not
`postgres`.

For a quick API cross-check, log in through the gateway (the token field is `accessToken`):

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$DRIVE_EMAIL\",\"password\":\"$DRIVE_PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")
```

## Devin Secrets Needed

- `DRIVE_EMAIL` — login email for the seeded RetailCo drive account.
- `DRIVE_PASSWORD` — password for that account.
