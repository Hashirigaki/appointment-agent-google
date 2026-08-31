# Submission Checklist

## Repository and safety

- [ ] Working tree reviewed; only intended submission artifacts are present.
- [ ] No `.env`, ADC file, identity token, private key, or credential is tracked.
- [ ] No personal email, service account email, project ID, or private service
      URL appears in public screenshots or submission copy.
- [ ] Cloud Run remains private; no `allUsers` invoker binding.
- [ ] Mock provider disclosure is visible in README, Devpost copy, and video.

## Technical proof

- [ ] `python .\scripts\run_mock.py` passes.
- [ ] `python .\scripts\run_adk_smoke.py` passes when network is available.
- [ ] `python .\scripts\run_adk_workflow_smoke.py` passes.
- [ ] `python .\scripts\run_firestore_workflow_smoke.py` passes.
- [ ] `python -m pip check` passes.
- [ ] Authenticated Cloud Run smoke reaches Turn 1
      `awaiting_human_approval` and Turn 2 `confirmed`.
- [ ] Tool order is `run_appointment_to_approval` then `confirm_appointment`.
- [ ] Firestore shows the same `run_id` in `confirmed` with no dangling refs.
- [ ] The same run has one trajectory, five semantic events, and three detail
      cards with valid run/detail links.
- [ ] Cloud Run logs contain no unhandled application error for the recorded run.

## Video

- [ ] Runtime is under four minutes.
- [ ] Problem and value proposition are stated in the first 30 seconds.
- [ ] Architecture names Gemini 3.5 Flash, Google ADK, Cloud Run, and Firestore.
- [ ] Turn 1 shows proposal slots and the human approval stop.
- [ ] Turn 2 shows the exact approved slot and confirmed appointment.
- [ ] Firestore confirmed document and Cloud Run private service proof are shown.
- [ ] Project IDs, emails, tokens, contact addresses, and unrelated browser tabs
      are cropped or blurred.
- [ ] If using the offline replay, it is labeled accurately.

## Devpost

- [ ] Project name, tagline, description, challenge, accomplishments, learning,
      and next steps are copied from `docs/devpost-submission.md` and edited for
      the final form limits.
- [ ] Repository link points to the intended public revision.
- [ ] Video link is accessible without requesting permission.
- [ ] Required Google technology selections and challenge category are complete.
- [ ] Final public repository commit and push happen only after review.

## Final live evidence

- [ ] Capture the verified deployed Turn 1/Turn 2 flow and matching Firestore
      run. Browser access to the private service is not required.
