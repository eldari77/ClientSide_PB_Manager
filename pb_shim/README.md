# Client-Side PB Shim

`ClientSidePBBridgeShim.cs` is the in-game request and command boundary for a
single bridge. It stages bounded snapshots and applies only the existing
allowlisted command envelopes.

## SOS Mode-Transition Request Ingress

Set all three CustomData fields to send one raw planning request to SOS:

```ini
sos_mode_transition_request_id=operator-cruise-001
sos_mode_transition_requested_mode=Cruise
sos_mode_transition_expires_sequence=120
```

Any blank field or an expiry of `0` omits the request. This is operator intent
for SOS planning only: it does not approve a plan, change the active mode,
create commands, or execute a transition. The existing exact-match PB approval
gate remains the sole boundary for its dedicated active-mode command envelope.
