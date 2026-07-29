import json
from pathlib import Path


AGE_FOLDERS = {
    "age1": "dark",
    "age2": "feudal",
    "age3": "castle",
    "age4": "imperial",
}
TECHNOLOGY_CATEGORIES = {"economy", "military"}


def resolve_templates_root(catalog_path, catalog, template_root=None):
    root = Path(template_root or catalog.get("templatesRoot") or "templates/tech")
    if not root.is_absolute():
        root = catalog_path.parent.parent / root
    return root


def discover_technology_templates(templates_root, default_civilization):
    discoveries = []
    for template_path in sorted(templates_root.rglob("*.png")):
        relative_path = template_path.relative_to(templates_root)
        parts = relative_path.parts
        if len(parts) == 3:
            civilization = default_civilization
            category, age_folder, _filename = parts
        elif len(parts) == 4:
            civilization, category, age_folder, _filename = parts
        else:
            continue

        if category not in TECHNOLOGY_CATEGORIES or age_folder not in AGE_FOLDERS:
            continue
        discoveries.append(
            {
                "civilization": civilization.lower(),
                "category": category,
                "ageAvailable": AGE_FOLDERS[age_folder],
                "template": relative_path.as_posix(),
                "templateStem": template_path.stem,
            }
        )
    return discoveries


def inject_technology_catalog(catalog_path, template_root=None, civilization="sis", prune=False):
    catalog_path = Path(catalog_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    templates_root = resolve_templates_root(catalog_path, catalog, template_root)
    discoveries = discover_technology_templates(templates_root, civilization)
    if not discoveries:
        raise RuntimeError(f"no technology templates found under {templates_root}")

    existing_by_stem = {}
    for entry in catalog.get("technologies", []):
        for template in entry.get("templates", []):
            existing_by_stem.setdefault(Path(template).stem, entry)

    injected = []
    discovered_stems = set()
    for discovery in discoveries:
        existing = existing_by_stem.get(discovery["templateStem"], {})
        discovered_stems.add(discovery["templateStem"])
        injected.append(
            {
                "key": existing.get("key", discovery["templateStem"]),
                "displayName": existing.get("displayName", discovery["templateStem"]),
                "civilization": discovery["civilization"],
                "category": discovery["category"],
                "ageAvailable": discovery["ageAvailable"],
                "building": existing.get("building"),
                "prerequisites": existing.get("prerequisites", []),
                "previewBeforeAge": existing.get("previewBeforeAge", False),
                "templates": [discovery["template"]],
            }
        )

    if not prune:
        for entry in catalog.get("technologies", []):
            stems = {Path(template).stem for template in entry.get("templates", [])}
            if stems.isdisjoint(discovered_stems):
                injected.append(entry)

    catalog["technologies"] = injected
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return {
        "catalog": str(catalog_path),
        "templatesRoot": str(templates_root),
        "technologyCount": len(injected),
        "discoveredTemplateCount": len(discoveries),
    }


def command_inject_technologies(args):
    result = inject_technology_catalog(
        args.catalog,
        template_root=args.template_root,
        civilization=args.civilization,
        prune=args.prune,
    )
    print(json.dumps(result, indent=2))
    return 0


def add_inject_technologies_args(parser):
    parser.add_argument("--catalog", default="data/technologies.json")
    parser.add_argument("--template-root")
    parser.add_argument("--civilization", default="sis")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="remove catalog entries whose template is no longer on disk",
    )
