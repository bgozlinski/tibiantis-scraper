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
  3. Relink BedmageWatch.character_id from losers to winner.
  4. Delete loser Character rows.
  5. UPDATE winner's name to canonical form (first-upper, rest-lower).

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
