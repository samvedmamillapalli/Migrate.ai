# Feature freeze & Devpost submit

## Freeze rules

- No new features after freeze — demo blockers only
- Tag: `hackathon-final` when path1 green + docs merged

## Devpost package

1. Public GitHub repo URL
2. Demo URL (from [DEPLOY_CHECKLIST.md](DEPLOY_CHECKLIST.md))
3. Video &lt;3 min (beats in [TALK_TRACK.md](TALK_TRACK.md))
4. Tool narrative: [docs/HACKATHON_TOOLS.md](../docs/HACKATHON_TOOLS.md)
5. One-line thesis: Predict → verify → grade → remember

## Day-of kit

- [ ] Fresh browser / incognito
- [ ] Owner identity set (`judge-demo`)
- [ ] `python scripts/dev.py doctor` + `/health` green
- [ ] SQL A/B on clipboard ([SQL_PLAYBOOK.md](SQL_PLAYBOOK.md))
- [ ] Backup laptop with same `.env`
- [ ] CloudWatch + Cockroach Cloud tabs open (secondary)
- [ ] Chaos lines printed ([CHAOS_BACKUPS.md](CHAOS_BACKUPS.md))

## Definition of done

- [x] Live path proven (PATH1 `99560180…` → grade + memory)
- [x] Second similar SQL retrieves prior graded memory (closed-loop HIT)
- [x] Abort/teardown practiced (`fc409451…` ABORT_OK)
- [x] Two CRDB tools + AWS named (landing + HACKATHON_TOOLS + Jobs observed UI)
- [x] Demo pack + README Demo section + video script
- [ ] Record &lt;3 min video from [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md) (human)
- [ ] Public deploy URL + Devpost submit (human — [DEPLOY_CHECKLIST.md](DEPLOY_CHECKLIST.md))
- [ ] Tag `hackathon-final` after committing this pack

## Tag (after commit)

```powershell
git tag -a hackathon-final -m "Hackathon final product freeze"
git push origin hackathon-final
```
