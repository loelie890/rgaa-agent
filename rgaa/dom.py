"""Arbre HTML, sélecteurs, patchs et sérialisation — bibliothèque standard.

Suffisant pour un audit sérieux et pour que l'agent *écrive* du HTML : il ne
choisit pas un correctif dans une liste, il fournit un sélecteur et une
opération, l'outil les applique réellement, puis l'audit revérifie.

Sélecteurs supportés : ``tag``, ``.classe``, ``#id``, ``[attr]``, ``[attr=valeur]``,
``:first-child``, combinaisons ``descendant`` et ``>``.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
TAG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]*$")


class DomError(Exception):
    pass


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "data")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, data: str = "") -> None:
        self.tag = tag
        self.attrs: dict[str, str] = attrs or {}
        self.children: list[Node] = []
        self.parent: Node | None = None
        self.data = data

    # -- construction ----------------------------------------------------- #
    def append(self, node: "Node") -> None:
        node.parent = self
        self.children.append(node)

    def insert(self, node: "Node", index: int) -> None:
        node.parent = self
        self.children.insert(index, node)

    # -- lecture ---------------------------------------------------------- #
    def elements(self) -> list["Node"]:
        return [child for child in self.children if child.tag != "#text"]

    def text(self) -> str:
        if self.tag == "#text":
            return self.data
        return "".join(child.text() for child in self.children)

    def descendants(self) -> list["Node"]:
        out: list[Node] = []
        for child in self.children:
            if child.tag == "#text":
                continue
            out.append(child)
            out.extend(child.descendants())
        return out

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    def classes(self) -> set[str]:
        return set(self.get("class").split())

    def index_in_parent(self) -> int:
        if not self.parent:
            return 0
        return self.parent.elements().index(self)

    def snippet(self, limit: int = 160) -> str:
        html = serialize_node(self)
        return html if len(html) <= limit else html[: limit - 1] + "…"

    # -- mutation --------------------------------------------------------- #
    def detach(self) -> None:
        if self.parent:
            self.parent.children.remove(self)
            self.parent = None

    def replace_with(self, nodes: list["Node"]) -> None:
        if not self.parent:
            raise DomError("nœud racine : remplacement impossible")
        index = self.parent.children.index(self)
        for offset, node in enumerate(nodes):
            node.parent = self.parent
            self.parent.children.insert(index + offset, node)
        self.parent.children.remove(self)
        self.parent = None


class Document:
    def __init__(self, root: Node, doctype: str) -> None:
        self.root = root
        self.doctype = doctype

    def serialize(self) -> str:
        head = self.doctype or "<!doctype html>"
        return head + "\n" + serialize_node(self.root) + "\n"

    def find(self, selector: str) -> list[Node]:
        return select(self.root, selector)


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]
        self.doctype = ""

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.doctype = f"<!{decl}>"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {name.lower(): (value if value is not None else "") for name, value in attrs})
        self.stack[-1].append(node)
        if node.tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {name.lower(): (value if value is not None else "") for name, value in attrs})
        self.stack[-1].append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return
        # balise fermante orpheline : on l'ignore plutôt que de casser l'arbre

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].append(Node("#text", data=data))


def parse(markup: str) -> Document:
    builder = _Builder()
    builder.feed(markup)
    builder.close()
    roots = builder.root.elements()
    root = roots[0] if roots else Node("html")
    return Document(root, builder.doctype)


def _escape_attr(value: str) -> str:
    """Échappement d'attribut : guillemet droit, chevrons et esperluette.

    On n'échappe pas l'apostrophe (inutile entre guillemets droits) : cela
    évite des diffs bruyants du type ``d&#x27;accès`` dans le mode CI.
    """
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def serialize_node(node: Node) -> str:
    if node.tag == "#text":
        return escape(node.data, quote=False)
    attrs = "".join(f' {name}="{_escape_attr(value)}"' for name, value in node.attrs.items())
    if node.tag in VOID:
        return f"<{node.tag}{attrs}>"
    inner = "".join(serialize_node(child) for child in node.children)
    return f"<{node.tag}{attrs}>{inner}</{node.tag}>"


# --------------------------------------------------------------------------- #
# Sélecteurs
# --------------------------------------------------------------------------- #
_ATTR_RE = re.compile(r"\[\s*([\w:-]+)\s*(?:=\s*[\"']?([^\"'\]]*)[\"']?)?\s*\]")
_PART_RE = re.compile(r"([a-zA-Z][\w-]*|\*)|#([\w-]+)|\.([\w-]+)|(\[[^\]]+\])|(:first-child|:last-child)")


class Compound:
    def __init__(self) -> None:
        self.tag: str | None = None
        self.ids: list[str] = []
        self.classes: list[str] = []
        self.attrs: list[tuple[str, str | None]] = []
        self.first = False
        self.last = False

    def matches(self, node: Node) -> bool:
        if self.tag and self.tag != "*" and node.tag != self.tag:
            return False
        for ident in self.ids:
            if node.get("id") != ident:
                return False
        classes = node.classes()
        for name in self.classes:
            if name not in classes:
                return False
        for name, value in self.attrs:
            if name not in node.attrs:
                return False
            if value is not None and node.get(name) != value:
                return False
        if self.first and node.index_in_parent() != 0:
            return False
        if self.last and node.parent and node.index_in_parent() != len(node.parent.elements()) - 1:
            return False
        return True


def _parse_compound(text: str) -> Compound:
    compound = Compound()
    position = 0
    while position < len(text):
        match = _PART_RE.match(text, position)
        if not match:
            raise DomError(f"sélecteur invalide près de {text[position:]!r}")
        tag, ident, klass, attr, pseudo = match.groups()
        if tag:
            compound.tag = tag
        elif ident:
            compound.ids.append(ident)
        elif klass:
            compound.classes.append(klass)
        elif attr:
            parsed = _ATTR_RE.match(attr)
            if not parsed:
                raise DomError(f"attribut invalide : {attr}")
            compound.attrs.append((parsed.group(1), parsed.group(2)))
        elif pseudo == ":first-child":
            compound.first = True
        elif pseudo == ":last-child":
            compound.last = True
        position = match.end()
    return compound


def parse_selector(selector: str) -> list[tuple[str, Compound]]:
    """Retourne [(combinateur, compound), ...] ; le premier combinateur est ''."""
    text = selector.strip()
    if not text:
        raise DomError("sélecteur vide")
    steps: list[tuple[str, Compound]] = []
    combinator = ""
    buffer = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == ">" :
            if buffer.strip():
                steps.append((combinator, _parse_compound(buffer.strip())))
                buffer = ""
            combinator = ">"
            index += 1
            continue
        if char.isspace():
            if buffer.strip():
                steps.append((combinator, _parse_compound(buffer.strip())))
                buffer = ""
                combinator = " "
            index += 1
            continue
        buffer += char
        index += 1
    if buffer.strip():
        steps.append((combinator, _parse_compound(buffer.strip())))
    if not steps:
        raise DomError("sélecteur vide")
    steps[0] = ("", steps[0][1])
    return steps


def select(root: Node, selector: str) -> list[Node]:
    current = [root]
    for combinator, compound in parse_selector(selector):
        found: list[Node] = []
        if combinator == ">":
            for node in current:
                found.extend(child for child in node.elements() if compound.matches(child))
        elif not combinator:
            if compound.matches(root):
                found.append(root)
            found.extend(node for node in [root] + root.descendants() if node is not root and compound.matches(node))
        else:
            for node in current:
                found.extend(child for child in node.descendants() if compound.matches(child))
        current = found
    seen: set[int] = set()
    unique = []
    for node in current:
        if id(node) not in seen:
            seen.add(id(node))
            unique.append(node)
    return unique


# --------------------------------------------------------------------------- #
# Patchs
# --------------------------------------------------------------------------- #
OPS = {
    "set_attr": "définit (ou remplace) un attribut — nécessite name et value",
    "remove_attr": "supprime un attribut — nécessite name",
    "set_text": "remplace le contenu texte de l'élément — nécessite value",
    "set_tag": "renomme la balise (h3 → h2, td → th, div → li) — nécessite value",
    "insert_html": "insère un fragment HTML autour de l'élément — nécessite name (before|after|prepend|append) et value",
}


def apply_patch(doc: Document, selector: str, op: str, name: str = "", value: str = "") -> dict:
    if op not in OPS:
        raise DomError(f"opération inconnue : {op!r} — valeurs acceptées : {', '.join(OPS)}")
    nodes = doc.find(selector)
    if not nodes:
        raise DomError(f"sélecteur sans correspondance : {selector!r}")
    before = nodes[0].snippet()
    changed = 0

    for node in nodes:
        if op == "set_attr":
            if not name:
                raise DomError("set_attr : name requis")
            if node.get(name) == value:
                continue
            node.attrs[name] = value
            changed += 1
        elif op == "remove_attr":
            if not name:
                raise DomError("remove_attr : name requis")
            if name not in node.attrs:
                continue
            del node.attrs[name]
            changed += 1
        elif op == "set_text":
            if not value.strip():
                raise DomError("set_text : value vide — un texte accessible ne peut pas être vide")
            if node.text().strip() == value.strip():
                continue
            node.children = [Node("#text", data=value)]
            node.children[0].parent = node
            changed += 1
        elif op == "set_tag":
            if not TAG_RE.match(value or ""):
                raise DomError(f"set_tag : balise invalide {value!r}")
            if node.tag == value:
                continue
            if node.tag in VOID or value in VOID:
                raise DomError("set_tag : impossible de convertir depuis ou vers une balise vide")
            node.tag = value
            changed += 1
        elif op == "insert_html":
            position = (name or "before").lower()
            if position not in {"before", "after", "prepend", "append"}:
                raise DomError("insert_html : name doit valoir before, after, prepend ou append")
            fragment = parse(f"<div>{value}</div>").root
            if fragment.tag != "div" or not fragment.children:
                raise DomError("insert_html : fragment vide")
            new_nodes = [child for child in fragment.children]
            if position in {"before", "after"}:
                parent = node.parent
                if not parent:
                    raise DomError("insert_html : élément racine, insertion impossible")
                index = parent.children.index(node)
                for offset, new_node in enumerate(new_nodes):
                    if position == "after":
                        index += 1
                    parent.insert(new_node, index + (offset if position == "before" else 0))
            else:
                if position == "prepend":
                    for offset, new_node in enumerate(new_nodes):
                        node.insert(new_node, offset)
                else:
                    for new_node in new_nodes:
                        node.append(new_node)
            changed += 1

    if not changed:
        raise DomError(
            "aucun changement appliqué : la valeur demandée est identique à l'existante "
            "(le correctif doit réellement modifier le document)"
        )
    return {"matched": len(nodes), "changed": changed, "before": before, "after": nodes[0].snippet()}
