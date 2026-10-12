# Real-recording validation references

One JSON reference per JamRecall recording, in `references/`, using the format in
`docs/research/real-recording-validation-protocol.md`. Recordings stay in `var/` and are not committed;
each reference names its session id and sha256. Assign dev/holdout **before** scoring and never move a
recording between splits afterwards.
