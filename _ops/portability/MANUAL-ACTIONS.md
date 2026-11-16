# Human actions only

No certificate, private-key or Keychain transfer has yet been established as necessary.
Do not add speculative transfers to this checklist. Installation commands, downloading,
cloning, path construction, checks, package verification and retries are agent work.

| When actually required | Human action | Why the agent stops | Agent completion/resume |
|---|---|---|---|
| New Mac: personal Codex or GitHub session is missing | Sign in and complete MFA in the vendor's own UI | The agent cannot supply your password/MFA or consent as you | Verify the expected personal identity with a bounded account/repository metadata read, then resume download/setup |
| New Mac: prerequisite installer requires OS authorization | Approve the specific installer or OS permission prompt after the agent explains its effect | macOS requires user authorization or an administrator password | Verify installed tool/version/permission and continue the prepared command |
| New Mac: a required personal service needs OAuth consent | Review and accept only the identified personal service/scopes | Consent is account-bound; old work tokens cannot be reused | Check account identity and a bounded read, then resume capability verification |
| Source or new Mac: an owner contract requires exact preview acceptance | Review the concrete operation and approve its bound digest | Governance requires a fresh explicit human decision for that operation | Recheck preimages/evidence, apply through the owner's interface, verify and resume |
| Only if a classified personal encrypted item cannot be recreated | Supply its recovery secret through a supported secure local mechanism | The agent cannot recover an unknown password, hardware-bound secret or required physical key presence | Perform the import/restore and digest/semantic verification; never put recovery material in chat or Git |

Unresolved source classification and native interoperability work are agent/owner engineering
tasks, not manual copying chores. The agent must explain any material architecture decision
needed to resolve them with a concrete proposal. A human approving this plan is not a substitute
for the missing technical evidence.
