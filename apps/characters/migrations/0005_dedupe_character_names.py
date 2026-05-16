"""Dedupe Character rows colliding under LOWER(name) before 0006 adds the
functional unique constraint.

M9.5-D47 first prod deploy surfaced that `/bedmage add Akrutki` and
`/bedmage add akrutki` produced two separate Character rows + two separate
BedmageWatch rows. The save() canonicalization shipped in this PR prevents
new collisions, but historical rows must be merged before the LOWER(name)
unique constraint (next migration, 0006) can apply — otherwise the CREATE
UNIQUE INDEX statement fails on existing duplicates.

Algorithm:
  1. Group Character rows by LOWER(name).
  2. For groups with >1 row, pick a winner (highest level — more info from
     the more recent scrape; tie-break lowest id — created first).
  3. Dedupe BedmageWatch per user across {winner, losers}: if a single user
     has watches on multiple case-variants (e.g. dev tested `/bedmage add
     Akrutki` + `/bedmage add akrutki` in the same Discord session — the
     M9.5-D47 reproduction scenario), keep the oldest watch (lowest id,
     created first) per (user, group) pair and delete the rest. Skipping
     this step causes the relink in #4 to produce two `(user, winner)`
     rows, violating BedmageWatch's
     `unique_bedmage_watch_per_user_character` constraint and aborting
     the migration.
  4. Relink surviving BedmageWatch.character_id from losers to winner.
  5. Delete loser Character rows.
  6. UPDATE winner's name to canonical form (first-upper, rest-lower).

The canonical-form UPDATE uses direct queryset UPDATE rather than save() —
migration code runs against a historical model snapshot where the save()
override defined in models.py is not available. Direct UPDATE is also more
efficient (no save() signal chain).

Idempotent: re-running on dedupe'd data is a no-op. Each group will have
size 1, so steps 2-4 are skipped, and step 5 is conditional on
`winner.name != canonical_name`.

Reverse: noop — once rows are merged, the original separate identities
cannot be reconstructed. Restoring the pre-merge state requires a backup.
"""

from django.db import migrations


def dedupe_character_names(apps, schema_editor):
    Character = apps.get_model("characters", "Character")
    BedmageWatch = apps.get_model("bedmages", "BedmageWatch")

    groups: dict[str, list] = {}
    for char in Character.objects.all():
        groups.setdefault(char.name.lower(), []).append(char)

    for canonical_key, rows in groups.items():
        if len(rows) > 1:
            rows.sort(key=lambda r: (-(r.level or 0), r.id))
            winner = rows[0]
            loser_ids = [r.id for r in rows[1:]]
            affected_character_ids = [winner.id, *loser_ids]

            # Per-user dedupe across the affected Character set. The unique
            # constraint `unique_bedmage_watch_per_user_character` on
            # BedmageWatch(user, character) would reject the relink below
            # if a single user had multiple watches across {winner, losers}.
            # Keep the lowest-id watch (oldest, created first) per user,
            # delete the rest.
            watches_by_user: dict[int, list[int]] = {}
            for watch in (
                BedmageWatch.objects.filter(character_id__in=affected_character_ids)
                .order_by("id")
                .only("id", "user_id")
            ):
                watches_by_user.setdefault(watch.user_id, []).append(watch.id)

            redundant_watch_ids: list[int] = []
            for ids_for_user in watches_by_user.values():
                if len(ids_for_user) > 1:
                    redundant_watch_ids.extend(ids_for_user[1:])

            if redundant_watch_ids:
                BedmageWatch.objects.filter(id__in=redundant_watch_ids).delete()

            BedmageWatch.objects.filter(character_id__in=loser_ids).update(
                character_id=winner.id
            )
            Character.objects.filter(id__in=loser_ids).delete()
        else:
            winner = rows[0]

        if not canonical_key:
            continue
        canonical_name = canonical_key[0].upper() + canonical_key[1:].lower()
        if winner.name != canonical_name:
            Character.objects.filter(id=winner.id).update(name=canonical_name)


class Migration(migrations.Migration):
    dependencies = [
        ("characters", "0004_allow_null_house_and_guild"),
        ("bedmages", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            dedupe_character_names,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
