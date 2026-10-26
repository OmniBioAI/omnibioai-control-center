# Source credential matrix

| Source ID | Signing contract | IAM requirements | Secret-manager reference | Runtime config | Rotation | Verification |
|---|---|---|---|---|---|---|
| github | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |
| rag | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |
| workbench | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |
| documentation | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |
| video | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |
| infrastructure | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |
| support | HMAC-SHA256 source/timestamp/nonce/body | source-specific event allowlist | MISSING | NOT_CONFIGURED | REQUIRED | NOT_VERIFIED |

The IDs follow the authoritative source inventory in the integration specification. Docker test-only credentials are randomly generated per run and are not production credentials.
