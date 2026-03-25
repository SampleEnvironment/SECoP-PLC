"""
Generates one PLCOpenXML file from the Structured Text files previously
emitted by the ST generators.

What this file does
-------------------
Reads every generated .st file from the st output directory and wraps
each one into the appropriate PLCOpenXML element.  The result is a single
.xml file that can be imported into any Codesys-based PLC IDE (Schneider
Electric Machine Expert, standard Codesys IDE, etc.) in one operation.

Design approach
---------------
The Codesys PLCOpenXML format stores each artefact's code in two ways:
  1. Structured XML elements (individual <variable> entries, typed fields …)
  2. InterfaceAsPlainText blocks — the full ST declaration as a plain-text
     string embedded in a <data> / <xhtml> element pair.

The IDE uses InterfaceAsPlainText as the authoritative source when it
reads back the file on import.  The structured XML elements are a secondary
representation used mainly for IDE tooling (autocomplete, etc.).

This generator therefore uses InterfaceAsPlainText as the sole content
carrier.  It does NOT reproduce the redundant structured variable lists.
This keeps the implementation simple and avoids needing to parse the ST
syntax beyond a minimal level (split declaration from body, detect the
EXTENDS / IMPLEMENTS keyword).

Artefact types handled
-----------------------
  ET_*              Enum data types
  ST_*              Struct data types (with EXTENDS inheritance)
  FB_Module_*       Function blocks (with EXTENDS inheritance)
  FB_SecopProcessModules  Special FB with IMPLEMENTS interface + METHOD Run
  SecopInit         Program (no VAR block)
  SecopMapFromPlc   Program (with local VAR block)
  SecopMapToPlc     Program (with local VAR block)
  GVL_SecNode       Global variable list (placed in project-level addData)

Output
------
One file:  <out_dir>/plcopenxml/SecNode.xml
"""

from __future__ import annotations

import re
import uuid
import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# XML namespace URIs used in Codesys PLCOpenXML files
# ---------------------------------------------------------------------------

_NS_IFACE      = "http://www.3s-software.com/plcopenxml/interfaceasplaintext"
_NS_ATTRS      = "http://www.3s-software.com/plcopenxml/attributes"
_NS_DT_INHERIT = "http://www.3s-software.com/plcopenxml/datatypeinheritance"
_NS_POU_INHERIT = "http://www.3s-software.com/plcopenxml/pouinheritance"
_NS_METHOD     = "http://www.3s-software.com/plcopenxml/method"
_NS_GLOBALVARS = "http://www.3s-software.com/plcopenxml/globalvars"
_NS_OBJECTID   = "http://www.3s-software.com/plcopenxml/objectid"
_NS_PROJSTRUCT = "http://www.3s-software.com/plcopenxml/projectstructure"
_NS_XHTML      = "http://www.w3.org/1999/xhtml"


# ---------------------------------------------------------------------------
# Low-level XML helpers
# ---------------------------------------------------------------------------

def _x(text: str) -> str:
    """Escape special XML characters in text content.

    The three mandatory XML escapes are applied:
      &  →  &amp;
      <  →  &lt;
      >  →  &gt;
    Single and double quotes do not need escaping in element content.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xhtml_block(content: str) -> str:
    """Return an <xhtml> element that carries the given ST text.

    The xhtml namespace declaration is included on the element so the
    IDE can identify it as HTML-compatible content.
    Angle brackets and ampersands inside *content* are XML-escaped.
    """
    return f'<xhtml xmlns="{_NS_XHTML}">{_x(content)}</xhtml>'


def _objectid_block(obj_id: str) -> str:
    """Return an objectid <data> block for an artefact.

    handleUnknown="discard" means the IDE ignores it if it cannot process
    it, but Machine Expert uses the ObjectId to assign a stable identity to
    each imported object and to resolve ProjectStructure folder references.
    """
    return (
        f'<data name="{_NS_OBJECTID}" handleUnknown="discard">'
        f'<ObjectId>{obj_id}</ObjectId>'
        f'</data>'
    )


def _iface_plaintext(st_text: str) -> str:
    """Return a complete InterfaceAsPlainText <data> block.

    This is the primary mechanism by which the Codesys IDE reads the
    artefact's declaration back on import.
    """
    return (
        f'<data name="{_NS_IFACE}" handleUnknown="implementation">'
        f'<InterfaceAsPlainText>{_xhtml_block(st_text)}</InterfaceAsPlainText>'
        f'</data>'
    )


# ---------------------------------------------------------------------------
# ST file parsing helpers
# ---------------------------------------------------------------------------

def _parse_enum_members(content: str) -> list[tuple[str, str]]:
    """Extract enum member names and integer values from an ET_ ST file.

    The ST enum syntax is:
        TYPE ET_Foo :
        (
            member_a := 0,
            member_b := 1
        );
        END_TYPE

    Returns a list of (name, value) string tuples in declaration order,
    e.g. [("member_a", "0"), ("member_b", "1")].
    Returns an empty list if the content cannot be parsed (non-fatal).
    """
    # Grab everything between the opening '(' and the closing ');'
    m = re.search(r"\(\s*(.*?)\s*\)", content, re.DOTALL)
    if not m:
        return []

    members: list[tuple[str, str]] = []
    for line in m.group(1).split("\n"):
        # Strip trailing comma and whitespace, then match  name := integer
        stripped = line.strip().rstrip(",")
        m2 = re.match(r"(\w+)\s*:=\s*(-?\d+)", stripped)
        if m2:
            members.append((m2.group(1), m2.group(2)))
    return members


def _last_end_var_idx(lines: list[str]) -> int:
    """Return the index of the last END_VAR line, or -1 if none found.

    Comparison is case-insensitive and ignores surrounding whitespace,
    which matches how Codesys Structured Text is written in practice.
    """
    last = -1
    for i, line in enumerate(lines):
        if line.strip().upper() == "END_VAR":
            last = i
    return last


def _extract_extends(first_line: str) -> str | None:
    """Extract the base type name from an EXTENDS clause.

    Works for both TYPE and FUNCTION_BLOCK declarations, e.g.:
      TYPE ST_Module_tc EXTENDS SECOP.ST_BaseModuleReadable :
      FUNCTION_BLOCK FB_Module_tc EXTENDS SECOP.FB_BaseModuleReadable

    Returns the base-type identifier, or None if not found.
    """
    m = re.search(r"\bEXTENDS\s+(\S+?)(?=\s|:|$)", first_line, re.IGNORECASE)
    if m:
        # Strip any trailing colon that the regex might have captured
        return m.group(1).rstrip(":")
    return None


def _extract_implements(first_line: str) -> str | None:
    """Extract the interface name from an IMPLEMENTS clause.

    Example:
      FUNCTION_BLOCK FB_SecopProcessModules IMPLEMENTS SECOP.I_ProcessModules

    Returns the interface identifier, or None if not found.
    """
    m = re.search(r"\bIMPLEMENTS\s+(\S+)", first_line, re.IGNORECASE)
    return m.group(1) if m else None


def _split_fb(content: str) -> tuple[str, str, str, str]:
    """Split a FUNCTION_BLOCK ST file into its four logical parts.

    Returns
    -------
    fb_decl : str
        The FB header line plus all VAR/END_VAR blocks that belong to the
        function block itself (up to the first METHOD keyword).
    fb_body : str
        Executable code between the FB's last END_VAR and the METHOD keyword.
        Empty for FB_SecopProcessModules, whose body lives in its method.
    method_decl : str
        The METHOD header plus its own VAR/END_VAR blocks.
        Empty string when the file contains no METHOD section.
    method_body : str
        Executable code inside the method body.
        Empty string when the file contains no METHOD section.
    """
    # Locate the METHOD keyword at the start of a line (case-insensitive)
    method_match = re.search(r"^METHOD\b", content, re.MULTILINE | re.IGNORECASE)

    if method_match:
        fb_part = content[: method_match.start()]
        method_part = content[method_match.start():]
    else:
        fb_part = content
        method_part = ""

    # --- FB: split at last END_VAR ---
    fb_lines = fb_part.split("\n")
    ev_idx = _last_end_var_idx(fb_lines)
    if ev_idx == -1:
        # Unusual: no VAR block at all — treat whole content as declaration
        fb_decl = fb_part.rstrip()
        fb_body = ""
    else:
        fb_decl = "\n".join(fb_lines[: ev_idx + 1])
        fb_body = "\n".join(fb_lines[ev_idx + 1:]).strip()

    if not method_part:
        return fb_decl, fb_body, "", ""

    # --- METHOD: split at last END_VAR ---
    method_lines = method_part.split("\n")
    ev_idx = _last_end_var_idx(method_lines)
    if ev_idx == -1:
        method_decl = method_part.rstrip()
        method_body = ""
    else:
        method_decl = "\n".join(method_lines[: ev_idx + 1])
        method_body = "\n".join(method_lines[ev_idx + 1:]).strip()

    return fb_decl, fb_body, method_decl, method_body


def _split_prg(content: str) -> tuple[str, str]:
    """Split a PROGRAM ST file into declaration and body.

    Returns
    -------
    prg_decl : str
        The PROGRAM <name> line, plus any VAR/END_VAR block that follows it.
        For programs without a VAR block (e.g. SecopInit) this is just the
        PROGRAM line followed by a newline.
    prg_body : str
        All executable code that follows the declaration.
    """
    lines = content.split("\n")
    ev_idx = _last_end_var_idx(lines)

    if ev_idx == -1:
        # No VAR block — declaration is only the first (PROGRAM) line
        prg_decl = lines[0].rstrip() + "\n"
        prg_body = "\n".join(lines[1:]).strip()
    else:
        prg_decl = "\n".join(lines[: ev_idx + 1])
        prg_body = "\n".join(lines[ev_idx + 1:]).strip()

    return prg_decl, prg_body


# ---------------------------------------------------------------------------
# Per-artefact XML fragment builders
# ---------------------------------------------------------------------------

def _build_enum_xml(name: str, content: str, obj_id: str) -> str:
    """Build a <dataType> element for an enum (ET_*) artefact.

    The PLCOpenXML schema requires at least one <value> child inside
    <values>, so we parse the enum members from the ST content and
    emit a proper <value name="..." value="..." /> for each one.

    The qualified_only and strict attributes are included because the
    generated ST files declare them and the IDE expects them on enums.
    """
    members = _parse_enum_members(content)
    values_xml = "".join(
        f'<value name="{n}" value="{v}" />'
        for n, v in members
    )

    return (
        f'<dataType name="{name}">'
        f'<baseType><enum><values>{values_xml}</values></enum></baseType>'
        f'<addData>'
        f'<data name="{_NS_ATTRS}" handleUnknown="implementation">'
        f'<Attributes>'
        f'<Attribute Name="qualified_only" Value="" />'
        f'<Attribute Name="strict" Value="" />'
        f'</Attributes>'
        f'</data>'
        f'{_iface_plaintext(content)}'
        f'{_objectid_block(obj_id)}'
        f'</addData>'
        f'</dataType>'
    )


def _build_struct_xml(name: str, content: str, obj_id: str) -> str:
    """Build a <dataType> element for a struct (ST_*) artefact.

    The inheritance (EXTENDS) is extracted from the first line and placed
    in a datatypeinheritance addData block, which is how the IDE stores it.
    The <baseType><struct> element is left empty — the IDE reads the
    field list from InterfaceAsPlainText.
    """
    first_line = content.split("\n")[0]
    extends = _extract_extends(first_line)

    inherit_block = ""
    if extends:
        inherit_block = (
            f'<data name="{_NS_DT_INHERIT}" handleUnknown="implementation">'
            f'<Inheritance><Extends>{extends}</Extends></Inheritance>'
            f'</data>'
        )

    return (
        f'<dataType name="{name}">'
        f'<baseType><struct /></baseType>'
        f'<addData>'
        f'{inherit_block}'
        f'{_iface_plaintext(content)}'
        f'{_objectid_block(obj_id)}'
        f'</addData>'
        f'</dataType>'
    )


def _build_fb_xml(
    name: str,
    content: str,
    obj_id: str,
    method_obj_id: str = "",
) -> str:
    """Build a <pou> element for a function block (FB_*) artefact.

    Handles two sub-cases automatically:
      - Regular FBs (FB_Module_*):  EXTENDS base class, non-empty body.
      - FB_SecopProcessModules:     IMPLEMENTS interface, empty FB body,
                                    METHOD Run with its own declaration + body.

    The inheritance keyword (EXTENDS or IMPLEMENTS) is extracted from the
    first declaration line and placed in a pouinheritance addData block.

    For FB_SecopProcessModules the METHOD Run section is embedded in a
    <data name="...method..."> block inside the FB's outer <addData>.
    The method_obj_id is set as an attribute on the <Method> element,
    which is how Codesys exports METHOD object identities.
    """
    fb_decl, fb_body, method_decl, method_body = _split_fb(content)
    first_line = fb_decl.split("\n")[0]

    extends   = _extract_extends(first_line)
    implements = _extract_implements(first_line)

    # Build the inheritance block for the <interface> addData
    if extends:
        inherit_block = (
            f'<data name="{_NS_POU_INHERIT}" handleUnknown="implementation">'
            f'<Inheritance><Extends>{extends}</Extends></Inheritance>'
            f'</data>'
        )
    elif implements:
        inherit_block = (
            f'<data name="{_NS_POU_INHERIT}" handleUnknown="implementation">'
            f'<Inheritance><Implements>{implements}</Implements></Inheritance>'
            f'</data>'
        )
    else:
        inherit_block = ""

    # The IDE reads the declaration from InterfaceAsPlainText only when it is
    # nested inside a variable-section addData (e.g. <localVars><addData>).
    # Placing it directly in <interface><addData> causes the IDE to show only
    # the first line.  This matches how Codesys exports FBs and how PRGs work.
    iface_section = (
        f'<interface>'
        f'<localVars>'
        f'<addData>{_iface_plaintext(fb_decl)}</addData>'
        f'</localVars>'
        # Inheritance stays in the interface-level addData (separate from vars)
        f'<addData>{inherit_block}</addData>'
        f'</interface>'
    )

    body_section = f'<body><ST>{_xhtml_block(fb_body)}</ST></body>'

    # Method section — only present for FB_SecopProcessModules
    if method_decl:
        # For the Method element the structure differs from the rest of the file:
        # - The interface uses <returnType> + <localVars><addData> pattern
        # - <InterfaceAsPlainText> is a DIRECT child of <Method> (not inside <data>)
        #   This is how Codesys exports METHOD elements.
        # - The method ObjectId is an attribute on <Method>, not a child data block.
        method_id_attr = f' ObjectId="{method_obj_id}"' if method_obj_id else ""
        method_section = (
            f'<addData>'
            f'<data name="{_NS_METHOD}" handleUnknown="implementation">'
            f'<Method name="Run"{method_id_attr}>'
            f'<interface>'
            f'<returnType><BOOL /></returnType>'
            f'<localVars>'
            f'<addData>{_iface_plaintext(method_decl)}</addData>'
            f'</localVars>'
            f'</interface>'
            f'<body><ST>{_xhtml_block(method_body)}</ST></body>'
            # Direct <InterfaceAsPlainText> child — not wrapped in <data name="...">
            f'<InterfaceAsPlainText>{_xhtml_block(method_decl)}</InterfaceAsPlainText>'
            f'<addData />'
            f'</Method>'
            f'</data>'
            # Repeat the FB declaration in the outer addData — Codesys exports it this way
            f'{_iface_plaintext(fb_decl)}'
            f'{_objectid_block(obj_id)}'
            f'</addData>'
        )
    else:
        # Regular FBs: no METHOD, but still need an outer <addData> with
        # InterfaceAsPlainText on the <pou> element.  The IDE uses that outer
        # block to populate the declaration pane; without it, the <localVars>
        # section (which has no individual <variable> elements) causes the IDE
        # to render an empty VAR/END_VAR block instead of the full declaration.
        method_section = f'<addData>{_iface_plaintext(fb_decl)}{_objectid_block(obj_id)}</addData>'

    return (
        f'<pou name="{name}" pouType="functionBlock">'
        f'{iface_section}'
        f'{body_section}'
        f'{method_section}'
        f'</pou>'
    )


def _build_prg_xml(name: str, content: str, obj_id: str) -> str:
    """Build a <pou> element for a program (PROGRAM ...) artefact.

    Handles two sub-cases:
      - No local VAR block (SecopInit):       <interface /> is empty.
      - With local VAR block (SecopMap*):     declaration goes inside
                                              <interface><localVars><addData>.

    In both cases the declaration is also repeated in the outer <addData>,
    which matches the pattern Codesys uses on export.
    """
    prg_decl, prg_body = _split_prg(content)
    has_var_block = "END_VAR" in prg_decl.upper()

    if has_var_block:
        # Programs with a local VAR block: embed declaration in <localVars>
        iface_section = (
            f'<interface>'
            f'<localVars>'
            f'<addData>{_iface_plaintext(prg_decl)}</addData>'
            f'</localVars>'
            f'</interface>'
        )
    else:
        # Programs without local variables: empty <interface />
        iface_section = "<interface />"

    body_section = f'<body><ST>{_xhtml_block(prg_body)}</ST></body>'

    # Declaration is always repeated in the outer addData block
    outer_adddata = f'<addData>{_iface_plaintext(prg_decl)}{_objectid_block(obj_id)}</addData>'

    return (
        f'<pou name="{name}" pouType="program">'
        f'{iface_section}'
        f'{body_section}'
        f'{outer_adddata}'
        f'</pou>'
    )


def _build_gvl_xml(name: str, content: str, obj_id: str) -> str:
    """Build the globalVars <data> block for the project-level <addData>.

    The GVL is not a POU — it lives in the project's addData section.
    Its qualified_only attribute is declared in an <Attributes> block.
    The full ST content is carried by InterfaceAsPlainText.
    """
    return (
        f'<data name="{_NS_GLOBALVARS}" handleUnknown="implementation">'
        f'<globalVars name="{name}">'
        f'<addData>'
        f'<data name="{_NS_ATTRS}" handleUnknown="implementation">'
        f'<Attributes><Attribute Name="qualified_only" Value="" /></Attributes>'
        f'</data>'
        f'{_iface_plaintext(content)}'
        f'{_objectid_block(obj_id)}'
        f'</addData>'
        f'</globalVars>'
        f'</data>'
    )


# ---------------------------------------------------------------------------
# Full document assembly
# ---------------------------------------------------------------------------

def _build_project_structure_xml(
    folder_name: str,
    objects: list[tuple[str, str, str]],
) -> str:
    """Build the ProjectStructure <data> block that defines the IDE folder layout.

    Parameters
    ----------
    folder_name :
        Name of the folder shown in the IDE project tree (e.g. "SecNode").
    objects :
        List of (name, obj_id, method_obj_id) tuples, one per artefact.
        method_obj_id is non-empty only for FB_SecopProcessModules, which
        has a Run method that appears as a child object in the folder.
    """
    items = ""
    for name, obj_id, method_obj_id in objects:
        if method_obj_id:
            # FB with a Method: the method appears as a child <Object>
            items += (
                f'<Object Name="{name}" ObjectId="{obj_id}">'
                f'<Object Name="Run" ObjectId="{method_obj_id}" />'
                f'</Object>'
            )
        else:
            items += f'<Object Name="{name}" ObjectId="{obj_id}" />'

    return (
        f'<data name="{_NS_PROJSTRUCT}" handleUnknown="discard">'
        f'<ProjectStructure>'
        f'<Folder Name="{folder_name}">'
        f'{items}'
        f'</Folder>'
        f'</ProjectStructure>'
        f'</data>'
    )


def _build_full_xml(
    node_name: str,
    timestamp: str,
    data_types_xml: str,
    pous_xml: str,
    gvl_xml: str,
    project_structure_xml: str,
) -> str:
    """Assemble the complete PLCOpenXML document string.

    Parameters
    ----------
    node_name :
        Name used in <contentHeader name="...">.
    timestamp :
        ISO-8601 datetime string for both creation and modification fields.
    data_types_xml :
        All <dataType> elements concatenated (enums then structs).
    pous_xml :
        All <pou> elements concatenated (FBs then programs).
    gvl_xml :
        The <data name="...globalvars..."> block for the GVL.
    project_structure_xml :
        The <data name="...projectstructure..."> block that defines the
        IDE folder layout.  Placed in the project-level <addData> alongside
        the GVL.
    """
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<project xmlns="http://www.plcopen.org/xml/tc6_0200">'
        f'<fileHeader'
        f' companyName=""'
        f' productName="SECoP PLC Code Generator"'
        f' productVersion="1.0"'
        f' creationDateTime="{timestamp}" />'
        f'<contentHeader'
        f' name="{node_name}"'
        f' version="0.0.0.0"'
        f' modificationDateTime="{timestamp}"'
        f' author="">'
        f'<coordinateInfo>'
        f'<fbd><scaling x="1" y="1" /></fbd>'
        f'<ld><scaling x="1" y="1" /></ld>'
        f'<sfc><scaling x="1" y="1" /></sfc>'
        f'</coordinateInfo>'
        f'</contentHeader>'
        f'<types>'
        f'<dataTypes>{data_types_xml}</dataTypes>'
        f'<pous>{pous_xml}</pous>'
        f'</types>'
        f'<instances><configurations /></instances>'
        f'<addData>{gvl_xml}{project_structure_xml}</addData>'
        f'</project>'
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def emit_plcopenxml(st_dir: Path, out_dir: Path, node_name: str = "SecNode") -> Path:
    """Generate one PLCOpenXML file from the ST artefacts in st_dir.

    Parameters
    ----------
    st_dir :
        Directory that contains the generated .st files.
        Expected layout:
          st_dir/GVL_SecNode.st
          st_dir/FB_SecopProcessModules.st
          st_dir/SecopInit.st
          st_dir/SecopMapFromPlc.st
          st_dir/SecopMapToPlc.st
          st_dir/modules/ET_Module_*.st
          st_dir/modules/ST_Module_*.st
          st_dir/modules/FB_Module_*.st
    out_dir :
        Root output directory.  The XML file is written to:
          out_dir/plcopenxml/<node_name>.xml
    node_name :
        Name embedded in the XML contentHeader and used as the output
        filename stem.  Defaults to "SECnode".

    Returns
    -------
    Path
        Absolute path to the generated XML file.
    """
    modules_dir = st_dir / "modules"

    # Collect artefacts in the desired XML order:
    #   1. enum types (ET_*)
    #   2. struct types (ST_*)
    #   3. module function blocks (FB_Module_*)
    #   4. FB_SecopProcessModules
    #   5. programs (SecopInit, SecopMapFromPlc, SecopMapToPlc)
    #   6. global variable list (GVL_SecNode) — goes to project addData, not types
    enums    = []
    structs  = []
    fb_mods  = []

    if modules_dir.exists():
        for st_file in sorted(modules_dir.glob("*.st")):
            name    = st_file.stem
            content = st_file.read_text(encoding="utf-8")
            if name.startswith("ET_"):
                enums.append((name, content))
            elif name.startswith("ST_"):
                structs.append((name, content))
            elif name.startswith("FB_"):
                fb_mods.append((name, content))

    # Core artefact files (always expected to exist after step 7 of the pipeline)
    core_fb   = st_dir / "FB_SecopProcessModules.st"
    core_prgs = [
        st_dir / "SecopInit.st",
        st_dir / "SecopMapFromPlc.st",
        st_dir / "SecopMapToPlc.st",
    ]
    core_gvl  = st_dir / "GVL_SecNode.st"

    # Each artefact gets a stable UUID so the IDE can assign it a persistent
    # identity and the ProjectStructure folder references are resolved correctly.
    # UUIDs are generated fresh on every run; that is fine because the IDE
    # replaces them with its own internal IDs when the file is imported.

    # --- Build the <dataTypes> section ---
    data_types_xml = ""
    # folder_objects collects (name, obj_id, method_obj_id) for ProjectStructure
    folder_objects: list[tuple[str, str, str]] = []

    for name, content in enums:
        obj_id = str(uuid.uuid4())
        data_types_xml += _build_enum_xml(name, content, obj_id)
        folder_objects.append((name, obj_id, ""))

    for name, content in structs:
        obj_id = str(uuid.uuid4())
        data_types_xml += _build_struct_xml(name, content, obj_id)
        folder_objects.append((name, obj_id, ""))

    # --- Build the <pous> section ---
    pous_xml = ""
    for name, content in fb_mods:
        obj_id = str(uuid.uuid4())
        pous_xml += _build_fb_xml(name, content, obj_id)
        folder_objects.append((name, obj_id, ""))

    if core_fb.exists():
        obj_id = str(uuid.uuid4())
        method_obj_id = str(uuid.uuid4())
        pous_xml += _build_fb_xml(
            "FB_SecopProcessModules",
            core_fb.read_text(encoding="utf-8"),
            obj_id,
            method_obj_id,
        )
        folder_objects.append(("FB_SecopProcessModules", obj_id, method_obj_id))

    for prg_file in core_prgs:
        if prg_file.exists():
            obj_id = str(uuid.uuid4())
            pous_xml += _build_prg_xml(
                prg_file.stem,
                prg_file.read_text(encoding="utf-8"),
                obj_id,
            )
            folder_objects.append((prg_file.stem, obj_id, ""))

    # --- Build the GVL block (goes into project-level <addData>) ---
    gvl_xml = ""
    if core_gvl.exists():
        obj_id = str(uuid.uuid4())
        gvl_xml = _build_gvl_xml("GVL_SecNode", core_gvl.read_text(encoding="utf-8"), obj_id)
        folder_objects.append(("GVL_SecNode", obj_id, ""))

    # --- Build the ProjectStructure block (IDE folder layout) ---
    project_structure_xml = _build_project_structure_xml(node_name, folder_objects)

    # --- Assemble the full XML document ---
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    xml = _build_full_xml(node_name, timestamp, data_types_xml, pous_xml, gvl_xml, project_structure_xml)

    # --- Write to disk ---
    out_plcopenxml_dir = out_dir / "plcopenxml"
    out_plcopenxml_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_plcopenxml_dir / f"{node_name}.xml"
    out_file.write_text(xml, encoding="utf-8")

    return out_file
