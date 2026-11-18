"""Écriture d'un classeur Excel (.xlsx) sans dépendance externe.

Un .xlsx est une archive zip de fichiers XML : ce module en écrit le strict
nécessaire — plusieurs feuilles, des styles (titre, en-tête, milliers,
pourcentages, dates), des largeurs de colonnes, un volet figé et un filtre
automatique. Assez pour livrer un tableau prêt à trier, filtrer et croiser,
là où un CSV arrive brut : sans séparateur de milliers, sans en-tête figé, et
avec ses lignes d'introduction mêlées au tableau.
"""
import io
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

from django.http import HttpResponse

TYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Indices des styles déclarés dans STYLES (cellXfs), dans cet ordre.
NORMAL, TITRE, ENTETE, ENTIER, POURCENT, DATE, AVERTISSEMENT, GRAS, DECIMAL, ENTIER_GRAS, DISCRET, NOTE = range(12)

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="4">
<numFmt numFmtId="164" formatCode="#,##0"/>
<numFmt numFmtId="165" formatCode="0.0&quot; %&quot;"/>
<numFmt numFmtId="166" formatCode="dd/mm/yyyy"/>
<numFmt numFmtId="167" formatCode="0.00"/>
</numFmts>
<fonts count="5">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><name val="Calibri"/></font>
<font><i/><sz val="11"/><color rgb="FFB45309"/><name val="Calibri"/></font>
<font><sz val="10"/><color rgb="FF6B7280"/><name val="Calibri"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFDBEAFE"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top/><bottom style="thin"><color rgb="FF93C5FD"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="12">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

_EPOQUE_EXCEL = date(1899, 12, 30)


def lettre_colonne(indice):
    """0 → A, 25 → Z, 26 → AA."""
    lettres = ""
    indice += 1
    while indice:
        indice, reste = divmod(indice - 1, 26)
        lettres = chr(65 + reste) + lettres
    return lettres


def style_par_defaut(valeur):
    if isinstance(valeur, bool):
        return NORMAL
    if isinstance(valeur, (date, datetime)):
        return DATE
    if isinstance(valeur, int):
        return ENTIER
    if isinstance(valeur, float):
        return DECIMAL
    return NORMAL


class Feuille:
    def __init__(self, nom):
        # Excel limite le nom d'une feuille à 31 caractères, sans : \ / ? * [ ]
        for interdit in ':\\/?*[]':
            nom = nom.replace(interdit, " ")
        self.nom = nom[:31]
        self.lignes = []
        self.largeurs = {}
        self.ligne_figee = None
        self.filtre = None
        self.paysage = False

    def ajouter(self, valeurs=(), styles=None):
        """Ajoute une ligne. `styles` : un style pour toute la ligne, une
        liste (un par cellule, None = style déduit de la valeur), ou rien."""
        if styles is None or isinstance(styles, int):
            styles = [styles] * len(valeurs)
        self.lignes.append(list(zip(valeurs, styles)))
        return len(self.lignes)  # numéro de ligne Excel (base 1)

    def ajuster_largeurs(self, minimum=8, maximum=45, a_partir_de=1):
        """Largeur de chaque colonne d'après son contenu le plus long, en
        ignorant les lignes d'introduction (titres longs sur une cellule)."""
        for numero, ligne in enumerate(self.lignes, start=1):
            if numero < a_partir_de:
                continue
            for indice, (valeur, style) in enumerate(ligne):
                if valeur is None:
                    continue
                if style == ENTETE:
                    # Un en-tête peut passer à la ligne : seul son mot le
                    # plus long impose une largeur.
                    longueur = max(len(mot) for mot in str(valeur).split())
                elif isinstance(valeur, (date, datetime)):
                    longueur = 10
                elif isinstance(valeur, int):
                    longueur = len(f"{valeur:,}")
                else:
                    longueur = max(len(morceau) for morceau in str(valeur).split("\n"))
                actuelle = self.largeurs.get(indice, minimum)
                self.largeurs[indice] = min(maximum, max(actuelle, longueur + 2))

    def _cellule(self, reference, valeur, style):
        if valeur is None or valeur == "":
            return f'<c r="{reference}" s="{style or 0}"/>' if style else ""
        style = style_par_defaut(valeur) if style is None else style
        if isinstance(valeur, bool):
            valeur = "oui" if valeur else "non"
        if isinstance(valeur, datetime):
            valeur = valeur.date()
        if isinstance(valeur, date):
            return f'<c r="{reference}" s="{style}"><v>{(valeur - _EPOQUE_EXCEL).days}</v></c>'
        if isinstance(valeur, (int, float)):
            return f'<c r="{reference}" s="{style}"><v>{valeur}</v></c>'
        texte = escape(str(valeur))
        return f'<c r="{reference}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{texte}</t></is></c>'

    def xml(self):
        morceaux = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        ]
        if self.paysage:
            morceaux.append('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
        if self.ligne_figee:
            morceaux.append(
                '<sheetViews><sheetView workbookViewId="0">'
                f'<pane ySplit="{self.ligne_figee}" topLeftCell="A{self.ligne_figee + 1}" '
                'activePane="bottomLeft" state="frozen"/>'
                '</sheetView></sheetViews>'
            )
        if self.largeurs:
            morceaux.append("<cols>")
            for indice in sorted(self.largeurs):
                morceaux.append(
                    f'<col min="{indice + 1}" max="{indice + 1}" width="{self.largeurs[indice]}" customWidth="1"/>'
                )
            morceaux.append("</cols>")
        morceaux.append("<sheetData>")
        for numero, ligne in enumerate(self.lignes, start=1):
            cellules = "".join(
                self._cellule(f"{lettre_colonne(indice)}{numero}", valeur, style)
                for indice, (valeur, style) in enumerate(ligne)
            )
            morceaux.append(f'<row r="{numero}">{cellules}</row>')
        morceaux.append("</sheetData>")
        if self.filtre:
            morceaux.append(f'<autoFilter ref="{self.filtre}"/>')
        if self.paysage:
            # À l'impression : paysage, toutes les colonnes sur une page en
            # largeur, autant de pages que nécessaire en hauteur.
            morceaux.append(
                '<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
                '<pageSetup orientation="landscape" paperSize="9" fitToWidth="1" fitToHeight="0"/>'
            )
        morceaux.append("</worksheet>")
        return "".join(morceaux)


class Classeur:
    def __init__(self):
        self.feuilles = []

    def feuille(self, nom):
        feuille = Feuille(nom)
        self.feuilles.append(feuille)
        return feuille

    def contenu(self):
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._types())
            archive.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            )
            archive.writestr("xl/workbook.xml", self._classeur())
            archive.writestr("xl/_rels/workbook.xml.rels", self._relations())
            archive.writestr("xl/styles.xml", STYLES)
            for numero, feuille in enumerate(self.feuilles, start=1):
                archive.writestr(f"xl/worksheets/sheet{numero}.xml", feuille.xml())
        return tampon.getvalue()

    def reponse(self, nom_fichier):
        reponse = HttpResponse(self.contenu(), content_type=TYPE_XLSX)
        reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
        return reponse

    def _types(self):
        feuilles = "".join(
            f'<Override PartName="/xl/worksheets/sheet{numero}.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for numero in range(1, len(self.feuilles) + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{feuilles}</Types>"
        )

    def _classeur(self):
        feuilles = "".join(
            f'<sheet name="{escape(feuille.nom, {chr(34): "&quot;"})}" sheetId="{numero}" r:id="rId{numero}"/>'
            for numero, feuille in enumerate(self.feuilles, start=1)
        )
        # Le filtre automatique d'Excel s'appuie sur ce nom défini caché.
        noms = "".join(
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="{numero}" hidden="1">'
            f"'{escape(feuille.nom)}'!{_absolu(feuille.filtre)}</definedName>"
            for numero, feuille in enumerate(self.feuilles)
            if feuille.filtre
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{feuilles}</sheets>"
            + (f"<definedNames>{noms}</definedNames>" if noms else "")
            + "</workbook>"
        )

    def _relations(self):
        feuilles = "".join(
            f'<Relationship Id="rId{numero}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="worksheets/sheet{numero}.xml"/>'
            for numero in range(1, len(self.feuilles) + 1)
        )
        styles = len(self.feuilles) + 1
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{feuilles}"
            f'<Relationship Id="rId{styles}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/styles" Target="styles.xml"/></Relationships>'
        )


def _absolu(reference):
    """« A5:V40 » → « $A$5:$V$40 »."""
    import re

    return re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", reference)
