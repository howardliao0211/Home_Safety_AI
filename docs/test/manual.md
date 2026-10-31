# Manual and device testing

Start the frontend, backend, and storage emulators using the
[local testing instructions](../../README.md#test-the-frontend-and-backend-locally).

## Connected assessment checklist

These checks call the selected model provider and consume model quota:

1. Choose **Assess a room**, select a photo or bundled sample, choose
   optional household profiles, and create an assessment.
2. Check that findings appear and that resolving or dismissing findings survives
   a browser reload.
3. Submit a linked follow-up and check that it updates the intended finding.
4. On analysis failure, check that the input remains available and the explicit
   **Retry** action repeats the operation.
5. Confirm deletion and check that the assessment is removed with its photos.

API mode retains assessment state and photos through the backend, scoped by the
signed-in Firebase account. Preview data stays on the device. Each mode uses separate
local state; reloads retain assessments and checklist actions. Starting a new
assessment retains earlier assessments. Return Home to reopen any saved assessment
from Previous assessments. A local draft can be resumed from Home; starting another
room asks before discarding it. See [Home/history checks](home-history.md).

## Frontend preview and devices

Run the following commands from `mobile/`.

### Browser preview without the backend

For fixture-only demos without the API, run:

```bash
EXPO_PUBLIC_DATA_SOURCE=preview npm run web
```

In preview mode only, **Preview** in the development header selects scenarios
or resets local preview data. The selected photo is not analysed in this mode.

### Android phone

```bash
npm start
```

Set `EXPO_PUBLIC_API_URL` to the development machine's reachable LAN address
with port 8000 and bind Uvicorn to `0.0.0.0`. For an Android emulator, use
`http://10.0.2.2:8000`. A phone's `localhost` refers to the phone itself.
Connect the phone and development machine to the same network, then scan the
terminal's QR code with Expo Go. If WSL networking or a firewall prevents the
phone from reaching the LAN address, use the installed tunnel support:

```bash
npm run start:tunnel
```

Tunneling requires internet access and exposes the development server through
a temporary public URL. It tunnels Expo only; the phone still needs a reachable
API URL. Stop the server when finished.

For an emulator, first configure Android Studio, the Android SDK, and `adb`,
start an emulator, then run `npm run android`.

See [demo notes](../demo.md) for recorded behavior, observed limitations, and
pending physical-device checks. These checks verify behavior rather than
hazard-detection accuracy.
