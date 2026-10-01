Real attestation chains (leaf first: cert0..cert3) from a development phone, chained to Google's
hardware attestation root. Copied from google/android-key-attestation
(src/test/resources/der/algorithm_{EC,RSA}_SecurityLevel_TEE), Apache License 2.0.
Expected facts (from that project's tests): attestation version 3, TEE, challenge "abc",
bootloader unlocked, verified boot state UNVERIFIED, OS patch level 2019-07.
