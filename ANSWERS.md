# Answers

## 1. What changes if the gateway itself controls active power at the grid connection point?

Today the gateway is a pass-through: the marketer decides, the gateway writes and verifies.As a plant controller it decides. It must hold a measured quantity (power at the connectionpoint, from a meter) at a setpoint or under a limit, and it must keep doing that when things fail. The difficulty grows in these places:

- **A control loop with measurement dynamics.** Meter latency, sampling time, inverter  ramp rates and load changes make it a closed loop. Stability, anti-windup and  oscillation between several inverters now matter. Stale data is no longer just a  flag: a stale meter value means the loop must switch to a defined safe state, not keep controlling on a guess.
- **Several devices, one setpoint.** Splitting a limit across inverters and batteries,  with devices that are offline, saturated or slower than others.
- **Safety and certification.** In Germany this is the VDE-AR-N 4110 plant controller(EZA-Regler): certified behaviour, defined response times, defined reaction to  communication loss and to the grid operator's setpoints. A bug can cause a  grid-code violation or a protection trip, not just lost revenue. Changes need review  and re-certification, not just a passing test suite.
- **Fallback gets harder.** The `hold` default above is acceptable for a pass-through  but not for a controller: if the meter is lost, holding the last setpoint while load  changes can exceed the connection limit. The failure behaviour has to be specified per  failure (meter, inverter, grid operator link), and tested for each.
- **Ownership of the limit.** Conflicting commands (marketer, grid operator, locallimit) need a defined priority.

## 2. How would I test the gateway on a real plant for the first time without risking the plant or the customer's revenue?

1. **Read-only first.** Connect with writes disabled at the code level (not just   unused). Compare gateway values against the inverter's display and the meter over   days: scaling, sign, word order, stale behaviour while unplugging the link.
2. **Agree the window.** A named person on site (qualified electrician), the customer and, if relevant, the marketer informed, a low-generation time, a rollback phone number, and a way to disable the gateway locally that does not need the gateway.
3. **First write: a harmless value.** Write the limit the inverter already has, read it   back, confirm it. Then a small step at midday only on a plant with headroom, and   return to the original value. Watch the real power output, not just the register.
4. **Test failures deliberately, in this order:** pull the Modbus cable, block IEC 104,   restart the gateway mid-limit, send out-of-range and non-integer values. Confirm each   behaves as the README says and the plant ends in a safe state.
5. **Limit the blast radius.** Start with the smallest or least critical plant, a clamp on the writable range in the gateway config (e.g. 80-100 %) for the first days, and a fast path to revert the limit register by hand.
6. **Run in shadow with the marketer** reading values only, before accepting real commands.
