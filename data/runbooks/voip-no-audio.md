---
id: voip-no-audio
category: voip
---
# Desk phone or softphone: no audio or one-way audio
Arabic: التلفون ما فيهو صوت، صوت من جهة واحدة، الطرف التاني ما بيسمعني، مكالمات، سنترال
1. Check the headset is plugged in and selected as the audio device in the softphone settings.
2. Test with an internal call to another extension; if internal calls work, the problem is the outside line.
3. One-way audio over VPN is usually NAT: disconnect the VPN, restart the softphone and test again.
4. Desk phone: unplug the network cable for 10 seconds; the phone re-registers with the PBX.
Escalate: if no calls work for anyone, check the "pbx" service and open a ticket (category voip, priority critical).
