`real_device.json`: an App Attest attestation and a later assertion from a real iPhone running a
development build (AAGUID "appattestdevelop") of the app `35MFYY2JY5.co.chiff.attestation-test`, chained to
Apple's App Attestation Root CA. Copied from bas-d/appattest (attestation/attestation_test.go and
assertion/assertion_test.go), BSD 3-Clause License, Copyright (c) 2019, Duo Labs.
The credential certificate was valid from 2021-04-14T09:55:20Z for three days, so the tests verify it at
that time. The attestation's clientData is "attestation-test"; the assertion's is
{"challenge":"assertion-test"} and its counter is 3. Base64 is URL-safe without padding, as in the source.
