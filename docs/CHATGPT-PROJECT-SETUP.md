# ChatGPT Project handoff and refresh instructions

Prepared: 2026-10-28. No ChatGPT Project upload or settings change is claimed.

## Install the matching reference pack

1. Create or open your NBA odds research ChatGPT Project.
2. Extract the supplied chatgpt-project-upload.zip locally.
3. Upload the individual files from its flat directory as Project sources:
   README.md, AGENTS.md, RECORDING-ENGINE-PROPOSAL.md, DATA-SPEC.md,
   ROADMAP-AND-PROGRESS.md, PRELIMINARY-CODE-REVIEW.md,
   CHATGPT-PROJECT-INSTRUCTIONS.md, CHATGPT-PROJECT-SETUP.md and PROJECT-SNAPSHOT.json.
   The ZIP is a transport package; upload the extracted files, not just the ZIP.
4. Paste the body under the title in CHATGPT-PROJECT-INSTRUCTIONS.md into the Project's
   instructions setting. An uploaded instruction document alone is not a verified setting.
5. Remove/replace older same-named planning sources to avoid conflicting versions.
6. Start a chat within that Project and use the verification prompt below.

Never upload legacy config.yaml, API keys, account information, production raw responses
or private databases. The pack intentionally contains planning/reference files only.

## Verification prompt

“Read PROJECT-SNAPSHOT.json and the uploaded NBA planning files. State the source GitHub
commit, the owner's confirmed recording requirements, proposed choices, unresolved
decisions, and the first development milestone. Confirm that development and live collection
have not started. Identify missing or conflicting files. If you cannot inspect a file or
calculate its hash, say so; do not claim hash verification.”

This checks context uptake, not a substitute for independently verifying byte equality.
The supplied manifest lists a SHA256 for each file, original repository path, source commit
and publication proof. Pack copies flatten docs/ filenames without changing their bytes;
repository-relative links inside those files refer to the GitHub layout.

## Version and refresh policy

GitHub remains canonical. Every handoff is an explicit snapshot, not assumed sync.
After updating GitHub: fetch each file at the exact new commit; copy its bytes to a flat
upload folder; compute SHA256; write a new PROJECT-SNAPSHOT.json; archive and verify entries;
replace the Project sources and re-check context. Do not mix files from different commits.
The manifest is generated after publication and is a delivery artifact, not a self-referencing
file that tries to contain its own Git commit/hash. Keep the manifest and archive with the
handoff locally; only approved documentation belongs in public GitHub.

## First development prompt (use when ready)

“Use the published planning baseline for aibuddygame/nba-arb-bot. Implement P01 only:
offline data schema, canonical identities and the game-relative slot planner. Inspect the
actual checkout and AGENTS.md first. Verify 25 slots, UTC/DST handling, restarts/idempotency,
late discovery, schedule revisions, cancellations and early starts. Use synthetic fixtures.
Do not activate live collection, subscriptions, email or trading. Report exact checks and
update progress only for demonstrated work.”

## Product guidance reference

[Official OpenAI Projects guidance](https://learn.chatgpt.com/docs/projects?surface=app).
Project files/instructions provide shared context. Interface labels can vary; verify the
actual uploaded sources and settings in your Project rather than infer installation from
prepared files.

