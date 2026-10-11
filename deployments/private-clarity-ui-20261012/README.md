# Private workspace clarity UI release

The user authorized publication of the reviewed private workspace layout on 2026-10-12. The frontend source is `8e1c07415e78db6b9ef199e997e501d1db4dc5e6` and the built version is `ecae2d8aa23a`.

The release changes priorities, cached funds navigation, period control layout, mail/advertising reading flows, and responsive detail sheets. It contains 22 frontend source/test changes and 113 built files. The CRM finance page, backend, provider access, credentials, private bank/Stripe calculations and API contracts are unchanged. No provider sync or AI processing is part of deployment.

The accepted live baseline is the currency UI release `adfb31c0b755`, with private backend `c1ae19b38fec8f62f044d4b0789f31662da12fbf`. The authenticated server preflight confirmed this baseline and healthy CRM/private API services. The older `/opt/t24-crm` checkout has pre-existing frontend changes and is not used or modified by this publisher.

Local verification completed: 212 private frontend tests, TypeScript checking, production build, and UI checks at widths 320, 390, 1024 and 1440. Source, build output, manifest and archive hashes were independently reconciled. Simulated local preview data is not production account data.

The publisher requires the fixed host, exact frozen artifacts, original backend evidence and the current currency static receipt. It uses a new protected release directory and public directory, retains prior assets, and switches only the Nginx static root. It rechecks runtime, schema, authorization and stable private records; it rolls back to the currency release if publication checks fail. Published success must additionally be checked in the authenticated owner UI.

Frozen artifact hashes:

- Manifest: `19b6b72ed7db9bfc52821777a511381f77035a4974cd89863ed1b9969f56d210`
- Payload: `51c5e12784dca30be0a0b5c4ba819fa5dcf6cec61ad8bb20d8d6be65d9b25d90`
- Prior static receipt: `dd7ccc6ee0d4273a281a7fb579ea871287305d41142b0363bc1624779ddeae48`

Preparation and offline testing do not prove production publication. The server result and owner UI evidence are recorded separately after execution.
