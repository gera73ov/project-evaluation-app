# -*- coding: utf-8 -*-
"""Сборка презентации «Приложение совместной оценки проектов».

Источник содержания: spec/SPEC.md v0.4 и макеты spec/img/*.png (только чтение).
Запуск: python3 build_presentation.py [путь_к_spec_img] [выходной.pptx]
"""
import os
import sys

from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml.ns import qn
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_IMG = sys.argv[1] if len(sys.argv) > 1 else "/mnt/project-files/spec/img"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "Приложение-оценки-проектов.pptx")
TMP_IMG = os.path.join(HERE, "img")
os.makedirs(TMP_IMG, exist_ok=True)

FONT = "Calibri"

# ---------- палитра ----------
NAVY = RGBColor(0x0E, 0x3B, 0x4A)
TEAL = RGBColor(0x1B, 0x6E, 0x80)
TEAL_L = RGBColor(0xE7, 0xF1, 0xF3)
TEAL_M = RGBColor(0xC9, 0xE0, 0xE5)
AMBER = RGBColor(0xD9, 0x8E, 0x04)
AMBER_L = RGBColor(0xFD, 0xF1, 0xD8)
INK = RGBColor(0x1F, 0x29, 0x33)
MUTED = RGBColor(0x5B, 0x67, 0x70)
LINE = RGBColor(0xD5, 0xDE, 0xE2)
BADGE = RGBColor(0x43, 0x38, 0xCA)
MONEY = RGBColor(0x6B, 0x4F, 0xBB)
MONEY_L = RGBColor(0xF0, 0xEC, 0xFA)
GREEN = RGBColor(0x2E, 0x7D, 0x4F)
GREEN_L = RGBColor(0xE3, 0xF3, 0xE8)
RED = RGBColor(0xB8, 0x3B, 0x2E)
GREY_L = RGBColor(0xEE, 0xF0, 0xF2)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SW, SH = 13.333, 7.5
LM = 0.6            # левое поле
CW = SW - 2 * LM    # ширина контента


# ---------- картинки ----------
def prep_image(name, crop=None, out_name=None):
    src = os.path.join(SRC_IMG, name)
    im = Image.open(src).convert("RGB")
    if crop:
        im = im.crop(crop)
    out = os.path.join(TMP_IMG, out_name or name)
    im.save(out, "PNG", optimize=True)
    return out, im.size


# ---------- текст ----------
def _set_run_font(run, size, bold=False, color=INK, italic=False):
    f = run.font
    f.name = FONT
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    rPr.set("lang", "ru-RU")
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", FONT)


def _bullet(p, char="•", color=TEAL, indent=0.22):
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(int(Inches(indent))))
    pPr.set("indent", str(-int(Inches(indent))))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    buClr = etree.SubElement(pPr, qn("a:buClr"))
    srgb = etree.SubElement(buClr, qn("a:srgbClr"))
    srgb.set("val", str(color))
    buFont = etree.SubElement(pPr, qn("a:buFont"))
    buFont.set("typeface", "Arial")
    bu = etree.SubElement(pPr, qn("a:buChar"))
    bu.set("char", char)


def text(slide, x, y, w, h, paras, size=14, color=INK, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, margin=0.0, space_after=0, bullets=False, line_spacing=None,
         name=None):
    """paras: str | list of (str | list of runs). run = (text, {opts})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    m = Inches(margin)
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = m
    tf.vertical_anchor = anchor
    if isinstance(paras, str):
        paras = [paras]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if space_after:
            p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        runs = para if isinstance(para, list) else [(para, {})]
        for rt, opts in runs:
            r = p.add_run()
            r.text = rt
            _set_run_font(r, opts.get("size", size), opts.get("bold", bold),
                          opts.get("color", color), opts.get("italic", False))
        if bullets:
            _bullet(p)
    return tb


def shape(slide, kind, x, y, w, h, fill=None, line=None, line_w=0.75, radius=None, name=None):
    sp = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        sp.name = name
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    st = sp._element.find(qn("p:style"))
    if st is not None:
        sp._element.remove(st)
    if radius is not None and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        sp.adjustments[0] = radius
    sp.text_frame.text = ""
    return sp


def card(slide, x, y, w, h, fill=TEAL_L, line=None, radius=0.06):
    return shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=fill, line=line, radius=radius)


def label_in(sp, txt, size=14, color=WHITE, bold=True, align=PP_ALIGN.CENTER):
    tf = sp.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = Inches(0.0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = txt
    _set_run_font(r, size, bold, color)


def circle(slide, x, y, d, txt, fill=TEAL, color=WHITE, size=14):
    sp = shape(slide, MSO_SHAPE.OVAL, x, y, d, d, fill=fill)
    label_in(sp, txt, size=size, color=color)
    return sp


def badge(slide, x, y, txt, h=0.32, size=12):
    w = max(h, 0.13 * len(txt) + 0.16)
    sp = shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=BADGE, radius=0.2)
    label_in(sp, txt, size=size)
    return w


def line(slide, x1, y1, x2, y2, color=LINE, width=1.5, arrow=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    st = c._element.find(qn("p:style"))
    if st is not None:
        c._element.remove(st)
    if arrow:
        ln = c.line._get_or_add_ln()
        tail = etree.SubElement(ln, qn("a:tailEnd"))
        tail.set("type", "triangle")
        tail.set("w", "med")
        tail.set("h", "med")
    return c


def picture(slide, path, size, x, y, max_w, max_h, border=True, align="left"):
    iw, ih = size
    k = min(max_w / iw, max_h / ih)
    w, h = iw * k, ih * k
    if align == "center":
        x = x + (max_w - w) / 2
    pic = slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(0.75)
    return pic, (x, y, w, h)


# ---------- каркас слайда ----------
prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]
SLIDES = []


def bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = color


def slide_number(slide, dark=False):
    tb = slide.shapes.add_textbox(Inches(SW - LM - 0.8), Inches(7.0), Inches(0.8), Inches(0.3))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    num = len(prs.slides._sldIdLst)
    fld = etree.SubElement(p._p, qn("a:fld"))
    fld.set("id", "{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}")
    fld.set("type", "slidenum")
    rPr = etree.SubElement(fld, qn("a:rPr"))
    rPr.set("lang", "ru-RU")
    rPr.set("sz", "1000")
    sf = etree.SubElement(rPr, qn("a:solidFill"))
    c = etree.SubElement(sf, qn("a:srgbClr"))
    c.set("val", "9FB3BB" if dark else "7B8790")
    lat = etree.SubElement(rPr, qn("a:latin"))
    lat.set("typeface", FONT)
    t = etree.SubElement(fld, qn("a:t"))
    t.text = str(num)


def footer(slide, dark=False):
    text(slide, LM, 7.0, 7, 0.3, "Приложение совместной оценки проектов · предложение к внедрению",
         size=10, color=RGBColor(0x9F, 0xB3, 0xBB) if dark else RGBColor(0x7B, 0x87, 0x90))
    slide_number(slide, dark)


def new_slide(title=None, notes="", dark=False, kicker=None):
    s = prs.slides.add_slide(BLANK)
    bg(s, NAVY if dark else WHITE)
    if title:
        if kicker:
            text(s, LM, 0.32, CW, 0.3, kicker.upper(), size=11, bold=True, color=AMBER)
        text(s, LM, 0.55 if kicker else 0.4, CW, 1.05, title, size=28, bold=True,
             color=WHITE if dark else NAVY, anchor=MSO_ANCHOR.TOP, name="Title")
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    SLIDES.append(title or "")
    return s


def legend(slide, items, x, y, w, row_h, num_w=0.62, label_size=14, desc_size=13):
    """items: (номер-выноски, заголовок, описание)."""
    for i, (n, head, desc) in enumerate(items):
        yy = y + i * row_h
        badge(slide, x, yy + 0.02, n)
        text(slide, x + num_w, yy, w - num_w, row_h - 0.05,
             [[(head, {"bold": True, "size": label_size, "color": INK})],
              [(desc, {"size": desc_size, "color": MUTED})]], space_after=1)


# =====================================================================
# Подготовка картинок
IMG = {}
IMG["work"] = prep_image("work.png", (0, 75, 3000, 1870), "work-top.png")
IMG["work_money"] = prep_image("work.png", (0, 1890, 3000, 2748), "work-money.png")
for n in ["home", "stats", "stats-totals", "stats-details", "stats-questions", "compare",
          "portfolio", "docs", "settings", "tree-menu"]:
    IMG[n] = prep_image(n + ".png")

# =====================================================================
# 1. Титул
s = new_slide(notes=(
    "Добрый день. Сегодня мы представляем приложение совместной оценки проектов, которое предлагается "
    "к внедрению в компании. Это инструмент, в котором модератор и эксперты разных дисциплин оценивают "
    "проект вместе и одновременно, а пресейл получает готовые цифры для коммерческого предложения. "
    "Мы пройдём по шагам: зачем это нужно, как устроена оценка, какие есть возможности и что нужно для запуска."),
    dark=True)
SLIDES[-1] = "Приложение совместной оценки проектов (титул)"
text(s, LM, 1.35, 6.2, 0.35, "ПРЕДЛОЖЕНИЕ К ВНЕДРЕНИЮ", size=13, bold=True, color=AMBER)
text(s, LM, 1.8, 6.3, 2.2, "Приложение совместной оценки проектов", size=44, bold=True, color=WHITE)
text(s, LM, 4.35, 6.0, 1.2,
     "Эксперты оценивают одновременно, итог и разброс видны сразу, "
     "пресейл получает готовые цифры для КП", size=18, color=RGBColor(0xCF, 0xE3, 0xE8))
text(s, LM, 6.3, 6.2, 0.4, "На основе спецификации требований, версия 0.4 · ноябрь 2026",
     size=12, color=RGBColor(0x9F, 0xB3, 0xBB))
p, _ = picture(s, IMG["work"][0], IMG["work"][1], 7.25, 1.35, 5.6, 4.9, border=False)
p.line.color.rgb = RGBColor(0x2C, 0x5F, 0x6E)
p.line.width = Pt(1)

# =====================================================================
# 2. Повестка
s = new_slide("О чём эта презентация", notes=(
    "Презентация построена от задачи к решению. Сначала — зачем компании единый инструмент оценки. "
    "Затем — как проходит оценка: роли, шаги, статусы и логика расчёта. Дальше — экраны приложения, "
    "ценность для каждой роли, коротко о безопасности и технологиях и в конце — план внедрения."))
agenda = [
    ("1", "Зачем это компании", "Задачи оценки проектов, которые решает приложение"),
    ("2", "Как устроена оценка", "Роли, шаги процесса, статусы, дерево и расчёт"),
    ("3", "Возможности приложения", "Рабочий экран, вопросы, статистика, снимки, портфель, документы"),
    ("4", "Ценность для ролей", "Что получает каждый участник — от эксперта до руководства"),
    ("5", "Безопасность и технологии", "Обзорно: защита коммерческих данных и где работает приложение"),
    ("6", "Внедрение", "Состав первой версии, приёмка, пилот и следующие шаги"),
]
for i, (n, h, d) in enumerate(agenda):
    col, row = i % 2, i // 2
    x = LM + col * 6.15
    y = 1.85 + row * 1.6
    card(s, x, y, 5.95, 1.35, fill=TEAL_L)
    circle(s, x + 0.3, y + 0.37, 0.62, n, size=20)
    text(s, x + 1.15, y + 0.25, 4.6, 0.45, h, size=20, bold=True, color=NAVY)
    text(s, x + 1.15, y + 0.7, 4.6, 0.6, d, size=14, color=MUTED)
footer(s)

# =====================================================================
# 3. Зачем
s = new_slide("От качества оценки зависит цена КП — и этой работе нужен единый инструмент",
              kicker="Зачем это компании", notes=(
    "Оценка проекта — это точка, где решается цена коммерческого предложения. Ошибка в одну сторону — "
    "проигрыш по цене, в другую — убыточный проект. При этом задача непростая: одну оценку собирают "
    "эксперты разных дисциplin, на старте много неопределённости, ответы заказчика меняют цифры, а ставки "
    "и деньги — коммерческая тайна. Приложение закрывает каждую из этих задач, дальше покажем как."))
tasks = [
    ("Много дисциплин — одна цифра", "Аналитика, бэкенд, фронтенд, QA, архитектура, DevOps оценивают свою часть, а итог нужен единый"),
    ("Неопределённость на старте", "Точной цифры нет: нужна вилка оценок и обоснованный запас на риск"),
    ("Вопросы к заказчику", "Ответы меняют оценку — их нельзя терять в почте и переписке"),
    ("Прозрачность правок", "Каждый должен видеть, кто и почему изменил цифру"),
    ("Сопоставимость и опыт", "Оценки разных проектов должны складываться, сравниваться и переиспользоваться"),
    ("Коммерческая тайна", "Ставки и деньги должны видеть только те, кому это положено"),
]
for i, (h, d) in enumerate(tasks):
    col, row = i % 3, i // 3
    w = (CW - 2 * 0.3) / 3
    x = LM + col * (w + 0.3)
    y = 1.85 + row * 2.45
    card(s, x, y, w, 2.15, fill=TEAL_L)
    circle(s, x + 0.3, y + 0.32, 0.55, str(i + 1), size=16)
    text(s, x + 1.05, y + 0.22, w - 1.3, 0.75, h, size=17, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, y + 1.1, w - 0.6, 1.0, d, size=14, color=INK)
footer(s)

# =====================================================================
# 4. Одной фразой
s = new_slide("Одной фразой: эксперты оценивают вместе, пресейл получает готовые цифры для КП",
              kicker="Что это за приложение", notes=(
    "Если сказать одной фразой: это единый инструмент, где модератор и эксперты одновременно и независимо "
    "оценивают проект в виде дерева, сразу видят итог и разброс, задают вопросы прямо у строки оценки, "
    "а модератор и пресейл получают готовые цифры, допущения и документы для КП. "
    "Четыре опоры приложения — на слайде; дальше разберём каждую."))
card(s, LM, 1.8, CW, 1.45, fill=NAVY)
text(s, LM + 0.45, 1.8, CW - 0.9, 1.45,
     "Один инструмент, в котором модератор и эксперты одновременно и независимо оценивают проект "
     "в виде дерева, видят итог и разброс в реальном времени, задают вопросы прямо у строки оценки, "
     "а модератор и пресейл получают готовые цифры, допущения и документы для КП",
     size=17, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
pillars = [
    ("Вместе и одновременно", "Каждый эксперт работает в своей дисциплине, правки коллег видны сразу, никто никого не ждёт"),
    ("Итог и разброс на лету", "Ожидаемая оценка и оценка с запасом на риск (P80, P90) пересчитываются при каждой правке"),
    ("Вопросы у строки оценки", "Обсуждения и вопросы заказчику привязаны к конкретной работе и не теряются"),
    ("Готово для КП", "Сумма с НДС и в валюте КП, допущения и риски, выгрузки в Excel и Word"),
]
w = (CW - 3 * 0.3) / 4
for i, (h, d) in enumerate(pillars):
    x = LM + i * (w + 0.3)
    y = 3.55
    card(s, x, y, w, 3.15, fill=TEAL_L)
    circle(s, x + 0.3, y + 0.3, 0.55, str(i + 1), fill=AMBER, size=17)
    text(s, x + 0.3, y + 1.0, w - 0.55, 0.75, h, size=17, bold=True, color=NAVY)
    text(s, x + 0.3, y + 1.75, w - 0.55, 1.35, d, size=14, color=INK)
footer(s)

# =====================================================================
# 5. Роли
s = new_slide("Шесть ролей делают оценку, ещё две отвечают за безопасность",
              kicker="Как устроена оценка · роли", notes=(
    "В приложении у каждого своя роль и свои права. Модератор владеет оценкой проекта, эксперты оценивают "
    "свои дисциплины, ревьюеры подтверждают качество, пресейл ведёт заказчика и видит деньги, руководитель "
    "пресейла видит весь портфель. Администратор ведёт общие справочники. Отдельно — суперадминистратор, "
    "который настраивает вход и безопасность, но не видит проекты и деньги, и аудитор ИБ, который читает "
    "журнал аудита. Важный принцип: эксперты денег не видят нигде."))
roles = [
    ("М", "Модератор", "Владелец оценки: создаёт проект, собирает команду, сводит итог, делает снимки и выгрузки", True),
    ("Э", "Эксперт", "Оценивает свою дисциплину в часах, задаёт вопросы коллегам и заказчику", False),
    ("Р", "Ревьюер", "Эксперт с правом отметки «Проверено» на оценках своей дисциплины", False),
    ("П", "Пресейл", "Общается с заказчиком, ведёт вопросы и ответы, видит деньги; оценку только читает", True),
    ("РП", "Руководитель пресейла", "Видит портфель всех проектов с деньгами, может войти в проект модератором", True),
    ("А", "Администратор", "Методолог: справочники фаз, дисциплин, типов работ и норм; пользователи", False),
]
w = (CW - 2 * 0.3) / 3
for i, (ab, h, d, money) in enumerate(roles):
    col, row = i % 3, i // 3
    x = LM + col * (w + 0.3)
    y = 1.8 + row * 1.75
    card(s, x, y, w, 1.55, fill=TEAL_L)
    circle(s, x + 0.25, y + 0.25, 0.62, ab, fill=TEAL, size=15)
    text(s, x + 1.05, y + 0.22, w - 1.2, 0.4, h, size=17, bold=True, color=NAVY)
    text(s, x + 1.05, y + 0.62, w - 1.2, 0.9, d, size=13, color=INK)
    if money:
        mp = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x + 0.15, y + 1.0, 0.82, 0.28, fill=MONEY_L, radius=0.3)
        label_in(mp, "₽ видит", size=11, color=MONEY)
y = 5.4
card(s, LM, y, CW, 1.4, fill=GREY_L)
text(s, LM + 0.3, y + 0.15, 3.2, 0.4, "Безопасность и контроль", size=15, bold=True, color=NAVY)
text(s, LM + 0.3, y + 0.55, 3.0, 0.8, "Не участвуют в оценке и не видят денег", size=13, color=MUTED)
circle(s, LM + 3.6, y + 0.4, 0.6, "СА", fill=NAVY, size=14)
text(s, LM + 4.35, y + 0.2, 3.5, 1.1,
     [[("Суперадминистратор", {"bold": True, "size": 15, "color": INK})],
      [("Настраивает способ входа и политики безопасности; проекты и деньги не видит", {"size": 13, "color": INK})]])
circle(s, LM + 8.05, y + 0.4, 0.6, "ИБ", fill=NAVY, size=14)
text(s, LM + 8.8, y + 0.2, 3.2, 1.1,
     [[("Аудитор ИБ", {"bold": True, "size": 15, "color": INK})],
      [("Независимо читает и выгружает весь журнал аудита", {"size": 13, "color": INK})]])
footer(s)

# =====================================================================
# 6. Процесс
s = new_slide("Путь оценки — от запроса заказчика до КП — укладывается в семь шагов",
              kicker="Как устроена оценка · процесс", notes=(
    "Вот как выглядит оценка шаг за шагом. Пресейл получает запрос и передаёт его модератору. Модератор "
    "создаёт проект, выбирает фазы, уровень детализации и дедлайн, назначает экспертов, ревьюеров и пресейла. "
    "Эксперты работают одновременно и независимо, вопросы к заказчику уходят пресейлу, ответы возвращаются "
    "прямо к строке. Модератор следит за готовностью и сводит оценку, делает снимок и выгружает данные для КП. "
    "Важно, что дерево остаётся живым: после ответов заказчика оценку можно уточнить и сделать снимок v2."))
steps = [
    ("Запрос", "Пресейл", "Получает запрос и ТЗ от заказчика и передаёт модератору"),
    ("Проект", "Модератор", "Создаёт проект: фазы, уровень детализации, дедлайн"),
    ("Команда", "Модератор", "Назначает экспертов по дисциплинам, ревьюеров и пресейла"),
    ("Оценка", "Эксперты", "Одновременно строят свои ветки и ставят оценки"),
    ("Вопросы", "Эксперты · пресейл", "Вопросы заказчику уходят пресейлу, ответы — к строке"),
    ("Сведение", "Модератор · ревьюеры", "Готовность, правки, отметки «Проверено»"),
    ("КП", "Модератор · пресейл", "Снимок, выгрузка с деньгами, передача пресейлу"),
]
n = len(steps)
colw = CW / n
cy = 2.15
line(s, LM + colw / 2, cy + 0.33, LM + CW - colw / 2, cy + 0.33, color=TEAL_M, width=3)
for i, (h, who, d) in enumerate(steps):
    cx = LM + i * colw
    circle(s, cx + colw / 2 - 0.33, cy, 0.66, str(i + 1), fill=AMBER if i == n - 1 else TEAL, size=18)
    text(s, cx + 0.05, cy + 0.85, colw - 0.1, 0.4, h, size=18, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
    pill = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, cx + 0.12, cy + 1.3, colw - 0.24, 0.5, fill=TEAL_L, radius=0.3)
    label_in(pill, who, size=11, color=TEAL)
    text(s, cx + 0.1, cy + 1.95, colw - 0.2, 1.6, d, size=13, color=INK, align=PP_ALIGN.CENTER)
card(s, LM, 5.85, CW, 0.9, fill=AMBER_L)
text(s, LM + 0.35, 5.85, CW - 0.7, 0.9,
     [[("Оценка остаётся живой. ", {"bold": True, "color": NAVY}),
       ("После ответов заказчика её можно доработать и сделать новый снимок — например, «v2 — после ответов заказчика».",
        {})]], size=15, anchor=MSO_ANCHOR.MIDDLE)
footer(s)

# =====================================================================
# 7. Статусы
s = new_slide("Статус проекта всегда показывает этап оценки и что можно делать",
              kicker="Как устроена оценка · статусы", notes=(
    "У проекта пять статусов. В подготовке проект видят только модераторы — они настраивают фазы и команду. "
    "Запуск оценки открывает проект команде и рассылает уведомления. Когда все ветки готовы, система "
    "предлагает перейти к сведению, но решение всегда за модератором. Завершённый проект доступен на чтение, "
    "при этом пресейл продолжает вести вопросы заказчику и результат пресейла. Удалить оценку через интерфейс "
    "нельзя: это база для будущих оценок и подтверждение того, что обещали заказчику. "
    "У каждой ветки дисциплины свой статус: «готово» нельзя поставить, пока есть пустые или неверные оценки, "
    "а любая правка цифры возвращает ветку в черновик и уведомляет модератора."))
stats = [
    ("Подготовка", GREY_L, MUTED, "Видят только модераторы: настройки, команда, фазы"),
    ("Оценка", TEAL_L, TEAL, "Работает вся команда, уведомления включены"),
    ("Сведение", AMBER_L, AMBER, "Модератор сводит и проверяет; правка «готовой» ветки вернёт её в черновик"),
    ("Завершена", GREEN_L, GREEN, "Только чтение; вопросы заказчику и результат пресейла ведутся дальше"),
    ("Архив", GREY_L, MUTED, "Через 180 дней или при отмене; чтение и копирование веток"),
]
bw, gap = 2.06, 0.45
for i, (h, fill, col, d) in enumerate(stats):
    x = LM + i * (bw + gap)
    b = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, 1.85, bw, 0.7, fill=fill, line=col, line_w=1.25, radius=0.25)
    label_in(b, h, size=17, color=col)
    text(s, x, 2.7, bw, 1.25, d, size=13, color=INK, align=PP_ALIGN.CENTER)
    if i < len(stats) - 1:
        line(s, x + bw + 0.06, 2.2, x + bw + gap - 0.06, 2.2, color=TEAL, width=2, arrow=True)
text(s, LM, 4.0, CW, 0.35,
     [[("Обратные переходы: ", {"bold": True, "color": NAVY}),
       ("«Вернуть в работу» из сведения · «Переоткрыть» завершённый · «Восстановить» из архива. "
        "Все переходы делает модератор и они пишутся в журнал.", {"color": MUTED})]], size=13)
card(s, LM, 4.6, CW, 2.2, fill=TEAL_L)
text(s, LM + 0.35, 4.75, 5, 0.4, "Статус ветки дисциплины", size=17, bold=True, color=NAVY)
bst = [("не начато", GREY_L, MUTED), ("черновик", AMBER_L, AMBER), ("готово", GREEN_L, GREEN), ("не нужно", WHITE, MUTED)]
for i, (h, fill, col) in enumerate(bst):
    x = LM + 0.35 + i * 1.6
    b = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, 5.3, 1.35, 0.45, fill=fill, line=col, radius=0.3)
    label_in(b, h, size=14, color=col)
text(s, LM + 7.0, 4.8, CW - 7.35, 1.95, [
    "«Готово» ставится, только если нет пустых и неверных оценок",
    "Любая правка цифры возвращает ветку в черновик и уведомляет модератора",
    "Открытые вопросы не мешают «готово», но видны рядом со статусом",
], size=14, bullets=True, space_after=6)
text(s, LM + 0.35, 5.95, 6.4, 0.75, "Модератор видит статус каждой пары «фаза × дисциплина» и сразу понимает, где оценка застряла",
     size=13, color=MUTED)
footer(s)

# =====================================================================
# 8. Дерево
s = new_slide("Оценка строится деревом с общими для всей компании фазами",
              kicker="Как устроена оценка · структура", notes=(
    "Оценка — это дерево. Сверху проект, под ним фазы из справочника компании: анализ и проектирование, "
    "разработка, тестирование, внедрение, гарантийная поддержка и управление проектом. Внутри фазы — "
    "дисциплины, это зона ответственности экспертов. Дальше эксперт сам раскладывает работу на модули, "
    "функции, экраны, интеграции, а оцениваются только листья. Поскольку фазы общие для всех, оценки "
    "разных проектов складываются и сравниваются, а ветки из прошлых проектов можно копировать."))
levels = [
    ("Проект", "«Портал дилеров»", NAVY),
    ("Фаза", "из справочника компании: «Разработка»", TEAL),
    ("Дисциплина", "зона экспертов: «Бэкенд»", TEAL),
    ("Узел", "модуль, экран, интеграция…: «Личный кабинет»", RGBColor(0x4E, 0x8F, 0x9D)),
    ("Лист", "оценка в часах, например 8–12–20", AMBER),
]
for i, (h, d, col) in enumerate(levels):
    x = LM + i * 0.42
    y = 1.85 + i * 0.98
    b = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 1.75, 0.62, fill=col, radius=0.25)
    label_in(b, h, size=15)
    text(s, x + 1.9, y - 0.05, 7.1 - (x + 1.9), 0.72, d, size=14, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    if i > 0:
        px = LM + (i - 1) * 0.42 + 0.2
        line(s, px, y - 0.36, px, y + 0.31, color=TEAL_M, width=1.5)
        line(s, px, y + 0.31, x, y + 0.31, color=TEAL_M, width=1.5)
card(s, 7.35, 1.85, SW - LM - 7.35, 4.85, fill=TEAL_L)
text(s, 7.7, 2.0, SW - LM - 8.05, 4.55, [
    [("Фазы — общий справочник. ", {"bold": True, "color": NAVY}), ("Оценки разных проектов складываются и сравниваются", {})],
    [("Дисциплина — уровень дерева. ", {"bold": True, "color": NAVY}), ("Ставку и ответственность не нужно указывать в каждой строке", {})],
    [("Типы работ с нормами. ", {"bold": True, "color": NAVY}), ("Подсказка «Норма: средний экран 5–7–10» — без автоподстановки", {})],
    [("Уровень детализации. ", {"bold": True, "color": NAVY}), ("Крупно, средне, детально; слишком крупные листья подсвечиваются", {})],
    [("Опыт не теряется. ", {"bold": True, "color": NAVY}), ("Ветку можно скопировать из прошлого проекта", {})],
], size=15, bullets=True, space_after=12, anchor=MSO_ANCHOR.MIDDLE)
footer(s)

# =====================================================================
# 9. Расчёт
s = new_slide("Три оценки вместо одной дают честную цифру с запасом на риск",
              kicker="Как устроена оценка · расчёт", notes=(
    "Эксперт ставит не одну цифру, а три: оптимистичную, реалистичную и пессимистичную. Из них приложение "
    "считает ожидаемую оценку и оценку с запасом — P80, то есть цифру, которую с вероятностью 80% не превысим. "
    "Какая цифра идёт в КП — E, P80 или P90 — выбирает модератор; по умолчанию P80. Управление проектом "
    "считается процентом от работ, по умолчанию 18%. Деньги считаются по ставкам дисциплин, в валюте КП, "
    "с НДС и без. Цифры на слайде — сквозной пример из спецификации, проект «Портал дилеров»."))
text(s, LM, 1.85, 6, 0.4, "Эксперт вводит для каждой работы", size=15, bold=True, color=NAVY)
orp = [("O", "оптимистично", "40"), ("R", "реалистично", "60"), ("P", "пессимистично", "100")]
for i, (k, d, v) in enumerate(orp):
    x = LM + i * 1.95
    card(s, x, 2.35, 1.75, 1.3, fill=TEAL_L)
    text(s, x, 2.42, 1.75, 0.6, [[(k + " ", {"bold": True, "color": TEAL, "size": 26}),
                                  (v + " ч", {"bold": True, "color": INK, "size": 22})]], align=PP_ALIGN.CENTER)
    text(s, x, 3.08, 1.75, 0.4, d, size=13, color=MUTED, align=PP_ALIGN.CENTER)
text(s, LM, 3.85, 5.7, 1.0,
     "Приложение считает ожидаемую оценку E и оценку с запасом на риск: P80 и P90 — цифры, "
     "которые с вероятностью 80% и 90% не будут превышены",
     size=14, color=INK)
text(s, LM, 4.95, 5.7, 1.9, [
    "Управление проектом — процент от работ (по умолчанию 18%)",
    "Деньги — по ставкам дисциплин, в валюте КП, с НДС и без",
    "Пустые и неверные оценки не входят в итог и подсвечиваются",
], size=14, bullets=True, space_after=6)
x0 = 6.75
text(s, x0, 1.85, 6, 0.4, "Итог проекта в примере «Портал дилеров»", size=15, bold=True, color=NAVY)
tiles = [("E", "406,5 ч", "ожидаемая оценка", TEAL_L, NAVY),
         ("P80", "425,5 ч", "идёт в КП (по умолчанию)", NAVY, WHITE),
         ("P90", "435,5 ч", "консервативная оценка", TEAL_L, NAVY)]
tw = (SW - LM - x0 - 0.4) / 3
for i, (k, v, d, fill, col) in enumerate(tiles):
    x = x0 + i * (tw + 0.2)
    card(s, x, 2.35, tw, 2.0, fill=fill)
    text(s, x, 2.5, tw, 0.4, k, size=16, bold=True, color=AMBER if fill == NAVY else TEAL, align=PP_ALIGN.CENTER)
    text(s, x, 2.9, tw, 0.7, v, size=30, bold=True, color=col, align=PP_ALIGN.CENTER)
    text(s, x + 0.1, 3.65, tw - 0.2, 0.6, d, size=12, color=col if fill == NAVY else MUTED, align=PP_ALIGN.CENTER)
card(s, x0, 4.6, SW - LM - x0, 2.15, fill=MONEY_L)
text(s, x0 + 0.3, 4.72, SW - LM - x0 - 0.6, 0.4, "Сумма для КП по P80 — видят только роли с деньгами", size=14, bold=True, color=MONEY)
money = [("1 200 495 ₽", "без НДС"), ("1 440 594 ₽", "с НДС 20%"), ("12 978 USD", "в валюте КП")]
mw = (SW - LM - x0 - 0.6) / 3
for i, (v, d) in enumerate(money):
    x = x0 + 0.3 + i * mw
    text(s, x, 5.25, mw - 0.1, 0.55, v, size=21, bold=True, color=MONEY)
    text(s, x, 5.8, mw - 0.1, 0.4, d, size=13, color=MUTED)
text(s, x0 + 0.3, 6.2, SW - LM - x0 - 0.6, 0.45, "Сумма строк по дисциплинам всегда сходится с итогом до рубля",
     size=12, color=MUTED)
footer(s)

# =====================================================================
# 10. Мои оценки
s = new_slide("«Мои оценки»: каждый сразу видит, где он нужен и что горит",
              kicker="Возможности · главный экран", notes=(
    "Работа начинается с экрана «Мои оценки». Здесь все проекты, где человек участвует, с его ролью, прогрессом "
    "по его веткам и дедлайном, который краснеет за два рабочих дня. Сверху — проекты, где есть вопросы лично мне. "
    "Колокольчик собирает вопросы, ответы заказчика и изменения модератора, а клик ведёт прямо к нужной строке. "
    "Письма приходят пачкой раз в 15 минут и ежедневной сводкой, и в них нет ни денег, ни оценок — только повод зайти."))
pic, (px, py, pw, ph) = picture(s, IMG["home"][0], IMG["home"][1], LM, 1.6, CW, 3.35, align="center")
items = [
    ("3", "Мой прогресс", "Сколько моих веток уже готово"),
    ("4", "Дедлайн", "Краснеет за 2 рабочих дня, если мои ветки не готовы"),
    ("5", "«Мне»", "Вопросы мне, ответы, изменения модератора"),
    ("6", "Уведомления", "Клик открывает нужную строку с обсуждением"),
    ("7", "Итог, ч", "Цифра для КП; сумма — только модератору и пресейлу"),
    ("2", "Создать проект", "Кнопка есть только у модераторов"),
]
cw3 = CW / 3
for i, (nn, h, d) in enumerate(items):
    col, row = i % 3, i // 3
    x = LM + col * cw3
    y = py + ph + 0.2 + row * 0.72
    badge(s, x, y + 0.03, nn)
    text(s, x + 0.5, y, cw3 - 0.6, 0.75, [[(h, {"bold": True, "size": 14})], [(d, {"size": 13, "color": MUTED})]])
footer(s)

# =====================================================================
# 11. Рабочий экран
s = new_slide("Рабочий экран — вся оценка в одном месте, сохранение на лету",
              kicker="Возможности · рабочий экран", notes=(
    "Это главный экран, на нём работают все роли. Сверху — итог проекта E, P80 и P90, цифра для КП отмечена "
    "плашкой. Фильтры позволяют эксперту видеть только свои ветки или только строки без оценки. У каждой ветки "
    "дисциплины свой статус и кнопка «Готово». Если коллега сейчас правит ячейку, она обведена его цветом — "
    "но занята только эта ячейка. Пустые и неверные оценки сразу видны и не попадают в итог. Обсуждение "
    "раскрывается прямо под строкой, там же — ответ заказчика. Кнопки «Сохранить» нет: всё сохраняется сразу. "
    "Номера на слайде совпадают с выносками на макете."))
pic, (px, py, pw, ph) = picture(s, IMG["work"][0], IMG["work"][1], LM, 1.75, 8.3, 5.1)
legend(s, [
    ("2", "Итог проекта", "E, P80, P90 по всему дереву; цифра «в КП» выделена"),
    ("5", "Фильтры", "«Мои ветки», «Без оценки», «Крупные», «С вопросами»"),
    ("7", "Ветка дисциплины", "Статус и кнопка «Готово» для эксперта"),
    ("8", "Правка коллеги", "Видна сразу; занята только одна ячейка"),
    ("9–10", "Ошибки на виду", "Пустые и неверные оценки не входят в итог"),
    ("14", "Обсуждение у строки", "Вопрос, события и ответ заказчика"),
], px + pw + 0.3, 1.8, SW - LM - (px + pw + 0.3), 0.84, num_w=0.75)
footer(s)

# =====================================================================
# 12. Совместная работа
s = new_slide("Совместная работа без очередей: занята только одна ячейка, а не строка",
              kicker="Возможности · совместная работа", notes=(
    "Главная идея приложения — эксперты работают одновременно. Правки коллег появляются у всех не дольше чем "
    "за секунду. Пока человек вводит значение, занята только эта ячейка, всё остальное свободно. Если двое "
    "изменили одно и то же поле, приложение покажет обе цифры и даст выбрать — ничего не потеряется. "
    "Правки модератора эксперт видит в ленте и в счётчике. Вместо отмены по Ctrl+Z есть история листа: кто, "
    "когда, что было и что стало, с возможностью вернуть прежнее значение."))
text(s, 8.55, 1.85, SW - LM - 8.55, 4.95, [
    [("Правки коллег ", {"bold": True, "color": NAVY}), ("появляются у всех без перезагрузки — не дольше 1 секунды", {})],
    [("Занята одна ячейка: ", {"bold": True, "color": NAVY}), ("рамка и инициалы коллеги, остальное правится параллельно", {})],
    [("Конфликт одного поля ", {"bold": True, "color": NAVY}), ("показывает обе цифры и даёт выбрать", {})],
    [("Правка модератора ", {"bold": True, "color": NAVY}), ("видна эксперту: событие в ленте и счётчик", {})],
    [("История вместо Ctrl+Z: ", {"bold": True, "color": NAVY}), ("кто, когда, было → стало, «Вернуть»", {})],
    [("Нет связи — ", {"bold": True, "color": NAVY}), ("жёлтая полоса и запрет ввода, правки не теряются молча", {})],
], size=14, bullets=True, space_after=9, anchor=MSO_ANCHOR.MIDDLE)
pic, (px, py, pw, ph) = picture(s, IMG["tree-menu"][0], IMG["tree-menu"][1], LM, 2.3, 7.6, 4.0)
text(s, LM, py + ph + 0.15, 7.6, 0.6,
     "Меню строки: добавить лист или узел, сменить тип, разбить, перенести, скопировать ветку из прошлого проекта; справа — история листа",
     size=12, color=MUTED)
footer(s)

# =====================================================================
# 13. Вопросы заказчику
s = new_slide("Вопросы заказчику рождаются у строки оценки и возвращаются к ней с ответом",
              kicker="Возможности · вопросы и обсуждения", notes=(
    "Обсуждение есть у любой строки дерева. Эксперт пишет вопрос, ставит флаг «нужен ответ» и адресата — "
    "коллегу, дисциплину, модератора или заказчика. Вопросы с адресатом «заказчик» попадают в единый список. "
    "Пресейл выбирает вопросы и выгружает их в Word или Excel, вопросы получают статус «отправлен». Ответ "
    "заказчика пресейл вносит в тот же вопрос, и автор сразу получает уведомление. В выгрузке нет денег "
    "и внутренних обсуждений. Для переговорных соображений у модератора и пресейла есть закрытые заметки, "
    "которых эксперты не видят."))
pic, (px, py, pw, ph) = picture(s, IMG["stats-questions"][0], IMG["stats-questions"][1], LM, 1.8, 8.3, 5.0)
legend(s, [
    ("1", "Статусы", "Новый → отправлен → отвечен → решён"),
    ("2", "Выгрузка", "Выбранные вопросы — в Word или Excel"),
    ("3", "Сквозной номер", "В-001, В-002… не меняется"),
    ("4", "Правка после отправки", "Помечается: пресейл знает, что ушло"),
    ("5", "Ответ заказчика", "Вносит пресейл, автор получает уведомление"),
    ("7", "Без лишнего", "В выгрузке нет денег и внутренних обсуждений"),
], px + pw + 0.3, 1.8, SW - LM - (px + pw + 0.3), 0.84)
footer(s)

# =====================================================================
# 14. Сетка готовности
s = new_slide("Сетка готовности показывает состояние всей оценки на одном экране",
              kicker="Возможности · статистика", notes=(
    "Статистика — экран модератора для управления оценкой. Сетка «фаза на дисциплину» показывает статус каждой "
    "ветки, её часы, кто и когда правил последним и флажки проблем: открытые вопросы, неучтённые листья, "
    "нет эксперта. Не начавшим экспертам можно напомнить одной кнопкой. Справа — итог проекта, контрольные "
    "соотношения, например QA к разработке в норме 25–35%, и доля часов, проверенных ревьюерами. "
    "Клик по любой ячейке ведёт на рабочий экран к этой ветке. Эксперт видит этот экран без денег."))
pic, (px, py, pw, ph) = picture(s, IMG["stats"][0], IMG["stats"][1], LM, 1.8, 8.4, 5.0)
legend(s, [
    ("3", "Черновик с флажками", "Открытые вопросы, неучтённые листья"),
    ("4", "Нет эксперта", "Сигнал модератору: ветку некому оценить"),
    ("7", "Напомнить", "Письмо не начавшим — одной кнопкой"),
    ("8", "Итог проекта", "Часы и деньги с НДС — роли с деньгами"),
    ("9", "Соотношения", "Например, QA к разработке: норма 25–35%"),
    ("10", "Проверено", "Доля проверенных ревьюерами часов"),
], px + pw + 0.3, 1.8, SW - LM - (px + pw + 0.3), 0.84, num_w=0.7)
footer(s)

# =====================================================================
# 15. Итоги
s = new_slide("Сумма для КП и её разбивка готовы без ручных расчётов",
              kicker="Возможности · итоги", notes=(
    "Вкладка «Итоги» отвечает на вопрос «сколько и из чего». По фазам и по дисциплинам видны ожидаемые часы, "
    "разброс, P80 и P90, доля и стоимость. Таблица «Сумма для КП» показывает три варианта цифры в рублях "
    "и в валюте, с НДС и без; выбранная для КП колонка выделена. График динамики показывает, как менялся итог "
    "по дням, с отметками снимков. Всё это выгружается в Excel. Эксперты видят ту же вкладку, но без денег."))
pic, (px, py, pw, ph) = picture(s, IMG["stats-totals"][0], IMG["stats-totals"][1], LM, 1.8, 8.4, 5.0)
legend(s, [
    ("1", "По фазам", "Часы, разброс, P80, P90, доля, стоимость"),
    ("2", "По дисциплинам", "Те же показатели плюс ставки"),
    ("3", "Сумма для КП", "E, P80, P90 в рублях и валюте, с НДС и без"),
    ("4", "Динамика итога", "Как менялась цифра по дням и снимкам"),
], px + pw + 0.3, 1.8, SW - LM - (px + pw + 0.3), 0.9)
card(s, px + pw + 0.3, 5.6, SW - LM - (px + pw + 0.3), 1.2, fill=MONEY_L)
text(s, px + pw + 0.5, 5.6, SW - LM - (px + pw + 0.7), 1.2,
     "Фиолетовое с замком видят только модератор, пресейл и руководитель пресейла", size=13, color=MONEY,
     anchor=MSO_ANCHOR.MIDDLE)
footer(s)

# =====================================================================
# 16. Качество оценки
s = new_slide("Статистика подсказывает, где оценку стоит уточнить, и готовит текст для КП",
              kicker="Возможности · качество оценки", notes=(
    "Остальные вкладки статистики помогают модератору проверить качество оценки. Доли дисциплин и контрольные "
    "соотношения показывают перекосы. Объёмы по типам дают строку для КП: сколько экранов, интеграций, тестов. "
    "Кандидаты на декомпозицию — самые крупные листья и самые широкие вилки, их стоит уточнить. Допущения и риски "
    "собираются из комментариев экспертов и выгружаются в Word как черновик раздела КП. Снимки — список "
    "зафиксированных версий оценки."))
pic, (px, py, pw, ph) = picture(s, IMG["stats-details"][0], IMG["stats-details"][1], LM, 1.75, 7.8, 5.1)
legend(s, [
    ("1", "Доли и соотношения", "Перекосы между дисциплинами видны сразу"),
    ("2", "Объёмы по типам", "Строка для КП: «Экран — 13, Интеграция — 1…»"),
    ("3", "Кандидаты на уточнение", "Крупные листья и широкие вилки оценок"),
    ("4", "Допущения и риски", "Черновик раздела КП с выгрузкой в Word"),
    ("5", "Снимки", "Зафиксированные версии оценки"),
], px + pw + 0.35, 1.8, SW - LM - (px + pw + 0.35), 0.95)
footer(s)

# =====================================================================
# 17. Сравнение
s = new_slide("Снимок фиксирует обещанное заказчику, сравнение объясняет каждое изменение",
              kicker="Возможности · снимки и сравнение", notes=(
    "Перед отправкой КП модератор делает снимок — неизменяемую копию оценки со ставками, курсом и настройками. "
    "Удалить или исправить снимок нельзя, можно только пометить ошибочным. Затем текущее состояние можно "
    "сравнить с любым снимком или два снимка между собой: видно, какие работы добавлены, удалены или изменены, "
    "кто и когда это сделал, на сколько изменился итог. В деньгах отдельно показан вклад изменения курса. "
    "Это готовый ответ на вопрос заказчика или руководства «почему цифра выросла». Цифры «было» на макете условные."))
pic, (px, py, pw, ph) = picture(s, IMG["compare"][0], IMG["compare"][1], LM, 1.85, 8.4, 4.9)
legend(s, [
    ("1", "Что с чем", "Текущее ↔ снимок или снимок ↔ снимок"),
    ("2", "Было → стало", "Часы и деньги; вклад курса отдельно"),
    ("3", "Вид изменения", "Добавлен, удалён, изменён, перемещён"),
    ("4", "Параметры", "Ставки, курс, НДС, процент управления"),
    ("5", "Экспорт", "Таблица сравнения — в Excel"),
], px + pw + 0.3, 1.85, SW - LM - (px + pw + 0.3), 0.9)
card(s, LM, py + ph + 0.3, pw, 1.0, fill=TEAL_L)
text(s, LM + 0.3, py + ph + 0.3, pw - 0.6, 1.0,
     [[("Снимок неизменяем: ", {"bold": True, "color": NAVY}),
       ("хранит дерево, расчёты, ставки, курс и настройки на момент отправки КП. "
        "Исправить или удалить его нельзя — только пометить ошибочным", {"color": INK})]], size=14,
     anchor=MSO_ANCHOR.MIDDLE)
footer(s)

# =====================================================================
# 18. Портфель
s = new_slide("Руководитель пресейла видит весь портфель: выигрыши, проигрыши и их причины",
              kicker="Возможности · портфель", notes=(
    "Для руководителя пресейла есть отдельный экран «Портфель». Здесь все проекты компании с деньгами, статусом "
    "и результатом пресейла: выигран, проигран или отменён заказчиком. Показатели — доля выигранных по числу и "
    "по деньгам, результаты по месяцам, причины проигрыша и отношение суммы договора к цифре КП. Это основа для "
    "калибровки норм и процента управления проектом. Руководитель может открыть любой проект на чтение или войти "
    "в него модератором; оба действия пишутся в журнал. Цифры на макете условные."))
pic, (px, py, pw, ph) = picture(s, IMG["portfolio"][0], IMG["portfolio"][1], LM, 1.75, 8.3, 5.1)
legend(s, [
    ("2", "Показатели", "Доля выигранных по числу и деньгам"),
    ("3", "По месяцам", "Выигран, проигран, нет итога"),
    ("4", "Причины проигрыша", "Цена, сроки, конкурент, отказ"),
    ("5", "Договор к КП", "Сколько уступили — калибровка норм"),
    ("6", "Реестр", "Все проекты с деньгами и результатом"),
    ("7", "Открыть / стать модератором", "Оба действия — в журнале аудита"),
], px + pw + 0.3, 1.8, SW - LM - (px + pw + 0.3), 0.84)
footer(s)

# =====================================================================
# 19. Настройки
s = new_slide("Модератор настраивает проект на одном экране: фазы, команда, деньги",
              kicker="Возможности · настройки проекта", notes=(
    "В настройках проекта модератор задаёт фазы, уровень детализации, дедлайн, процент управления проектом "
    "и выбирает цифру для КП. В блоке команды он добавляет дисциплины и назначает экспертов — в режиме Active "
    "Directory человека можно найти по ФИО и сразу добавить. Если участник заблокирован, его можно заменить, "
    "и открытые вопросы перейдут к замене. Блок «Деньги» с валютой, курсом, НДС и ставками видят только модератор, "
    "пресейл и руководитель пресейла; эксперты не видят его вообще."))
pic, (px, py, pw, ph) = picture(s, IMG["settings"][0], IMG["settings"][1], LM, 1.75, 6.5, 5.1)
legend(s, [
    ("2", "Основное", "Название, заказчик, фазы, детализация, дедлайн"),
    ("11", "Цифра для КП", "E, P80 или P90 и срок в неделях"),
    ("4", "Добавить дисциплину", "Ветки сразу появляются во всех фазах"),
    ("16", "Найти в AD", "Человек находится по ФИО и сразу в команде"),
    ("12", "Замена участника", "Роли и открытые вопросы переходят к замене"),
    ("7", "Деньги", "Валюта, курс, НДС, ставки — не для экспертов"),
], px + pw + 0.4, 1.8, SW - LM - (px + pw + 0.4), 0.84, num_w=0.7)
footer(s)

# =====================================================================
# 20. Документы и выгрузки
s = new_slide("Документы заказчика и выгрузки для КП — в проекте и под контролем",
              kicker="Возможности · документы и экспорт", notes=(
    "Документы заказчика — ТЗ, таблицы, презентации — загружаются прямо в проект. Каждый файл проверяется "
    "антивирусом, хранится зашифрованным, а каждое скачивание пишется в журнал. В обсуждениях файлы не "
    "прикладываются — только ссылка на документ проекта. Выгрузки покрывают все нужды КП: Excel с часами для "
    "всех участников, Excel с деньгами и отдельным листом «Для КП», вопросы заказчику в Word или Excel, "
    "черновик допущений и рисков. На каждой выгрузке — гриф «Коммерческая тайна», ФИО выгрузившего и дата."))
pic, (px, py, pw, ph) = picture(s, IMG["docs"][0], IMG["docs"][1], LM, 1.75, 8.3, 3.55)
legend(s, [
    ("1", "Загрузка", "PDF, DOCX, XLSX до 50 МБ, без макросов"),
    ("2–3", "Антивирус", "Файл доступен только после проверки"),
    ("5", "Кто что может", "Загружают модератор и пресейл"),
    ("6", "Ссылка в обсуждении", "Вместо вложений — ссылка на документ"),
], px + pw + 0.3, 1.8, SW - LM - (px + pw + 0.3), 0.92, num_w=0.7)
exp = [("Excel «Часы»", "Для всех участников"),
       ("Excel «С деньгами»", "Лист «Для КП» с разбивкой"),
       ("Вопросы заказчику", "Word или Excel"),
       ("Допущения и риски", "Черновик раздела КП в Word")]
ew = (CW - 3 * 0.25) / 4
for i, (h, d) in enumerate(exp):
    x = LM + i * (ew + 0.25)
    card(s, x, 5.85, ew, 0.95, fill=TEAL_L)
    text(s, x + 0.2, 5.92, ew - 0.4, 0.85, [[(h, {"bold": True, "size": 15, "color": NAVY})],
                                           [(d, {"size": 13, "color": MUTED})]], anchor=MSO_ANCHOR.MIDDLE)
text(s, LM, 5.48, CW, 0.3, "На каждой выгрузке — гриф «Коммерческая тайна», ФИО выгрузившего, дата и время",
     size=12, color=MUTED)
footer(s)

# =====================================================================
# 21. Ценность по ролям
s = new_slide("Каждая роль получает своё: от точной цифры для КП до управления портфелем",
              kicker="Ценность для ролей", notes=(
    "Подведём итог по ролям. Руководство и руководитель пресейла получают прозрачный портфель и данные для "
    "решений о ценах. Пресейл — готовую цифру с разбивкой и управляемый список вопросов. Модератор — контроль "
    "над готовностью и качеством оценки. Эксперт — простой инструмент, где он работает только в своих ветках; "
    "цель — первый заполненный лист без обучения за 10 минут. Ревьюеры и руководители направлений участвуют "
    "в проектах как ревьюеры или эксперты своей дисциплины и видят долю проверенных часов. Администратор "
    "ведёт единую методику, а служба ИБ получает полный журнал и контроль доступа к деньгам."))
vals = [
    ("РП", "Руководство и руководитель пресейла", ["Портфель всех проектов с деньгами", "Доля выигранных, причины проигрыша", "Договор к цифре КП — калибровка цен"]),
    ("П", "Пресейл", ["Готовая цифра для КП с разбивкой", "Вопросы заказчику одним файлом", "Закрытые заметки для переговоров"]),
    ("М", "Модератор", ["Сетка готовности и напоминания", "Снимки и сравнение версий", "Экспорт с деньгами в один клик"]),
    ("Э", "Эксперты", ["Работа только в своих ветках", "Нормы-подсказки, быстрый ввод", "Вопросы и ответы прямо у строки"]),
    ("Р", "Ревьюеры и руководители направлений", ["Отметка «Проверено» на оценках", "Доля проверенных часов", "Контрольные соотношения дисциплин"]),
    ("А", "Администратор и служба ИБ", ["Единые фазы, типы работ и нормы", "Журнал аудита и передача в SIEM", "Деньги изолированы по ролям"]),
]
w = (CW - 2 * 0.3) / 3
for i, (ab, h, pts) in enumerate(vals):
    col, row = i % 3, i // 3
    x = LM + col * (w + 0.3)
    y = 1.8 + row * 2.55
    card(s, x, y, w, 2.35, fill=TEAL_L)
    circle(s, x + 0.25, y + 0.22, 0.58, ab, fill=AMBER if i == 0 else TEAL, size=14)
    text(s, x + 0.98, y + 0.18, w - 1.15, 0.66, h, size=15, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, y + 1.0, w - 0.5, 1.3, pts, size=14, bullets=True, space_after=3)
footer(s)

# =====================================================================
# 22. Безопасность
s = new_slide("Коммерческие данные защищены: доступ по ролям, деньги — только у тех, кому положено",
              kicker="Безопасность и доступ · обзор", notes=(
    "Коротко о безопасности. Приложение доступно только из офисной сети и через VPN. Вход — через учётную "
    "запись Active Directory или приложения, второй фактор назначается по ролям, а деньги показываются только "
    "после его ввода. Права проверяются на сервере на каждое действие: эксперт не получит ставки даже через API. "
    "Администраторы по должности денег не видят. Все значимые действия пишутся в неизменяемый журнал аудита, "
    "который передаётся в SIEM. Перед вводом в эксплуатацию приложение проверяет служба ИБ."))
sec = [
    ("Только внутренний контур", "Офисная сеть и VPN, из интернета недоступно"),
    ("Вход и второй фактор", "Active Directory или учётка приложения; TOTP по ролям, деньги — только после него"),
    ("Права на сервере", "Каждое действие проверяется; лишние данные не отдаются даже в API"),
    ("Разделение обязанностей", "Администраторы по должности не видят ставки и деньги"),
    ("Неизменяемый журнал", "Аудит всех значимых действий, передача в SIEM, аудитор ИБ"),
    ("Файлы и письма", "Антивирус и шифрование документов; в письмах нет цифр"),
]
for i, (h, d) in enumerate(sec):
    y = 1.8 + i * 0.83
    circle(s, LM, y + 0.05, 0.48, str(i + 1), size=14)
    text(s, LM + 0.7, y, 5.9, 0.82, [[(h, {"bold": True, "size": 15, "color": NAVY})],
                                     [(d, {"size": 13, "color": INK})]])
x0 = 7.25
text(s, x0, 1.8, SW - LM - x0, 0.35, "Кто видит деньги", size=15, bold=True, color=NAVY)
yes = ["Модератор проекта", "Пресейл проекта", "Руководитель пресейла"]
no = ["Эксперты и ревьюеры", "Администратор*", "Суперадминистратор, аудитор ИБ"]
hw = (SW - LM - x0 - 0.2) / 2
card(s, x0, 2.2, hw, 1.55, fill=MONEY_L)
card(s, x0 + hw + 0.2, 2.2, hw, 1.55, fill=GREY_L)
text(s, x0 + 0.2, 2.3, hw - 0.3, 1.4, [[("Видят", {"bold": True, "color": MONEY})]] + [[(t, {})] for t in yes], size=13)
text(s, x0 + hw + 0.4, 2.3, hw - 0.3, 1.4, [[("Не видят", {"bold": True, "color": MUTED})]] + [[(t, {})] for t in no], size=13)
text(s, x0, 3.8, SW - LM - x0, 0.3, "* только если сам назначен участником проекта — с записью в аудит", size=11, color=MUTED)
pic, (px, py, pw, ph) = picture(s, IMG["work_money"][0], IMG["work_money"][1], x0, 4.25, SW - LM - x0, 2.0)
text(s, x0, py + ph + 0.08, SW - LM - x0, 0.45,
     "У модератора: сумма в КП и закрытые заметки (фиолетовым). У эксперта этих элементов нет",
     size=11, color=MUTED)
footer(s)

# =====================================================================
# 23. Технологии
s = new_slide("Приложение работает во внутреннем контуре компании на одном сервере",
              kicker="Технологии и эксплуатация · обзор", notes=(
    "Для тех, кому важны технологии. Приложение построено на распространённом открытом стеке: Python и FastAPI "
    "на сервере, PostgreSQL и Redis для данных, React в браузере. Разворачивается на одном Linux-сервере в Docker, "
    "подходят в том числе Astra Linux и РЕД ОС. Целевые показатели: правка коллеги доходит до всех за секунду, "
    "проект на 2000 строк открывается за 2 секунды, доступность в рабочее время 99%. Серверы и резервные копии "
    "ведёт служба эксплуатации ИТ, развитие и сопровождение — своя команда разработки."))
stack = [
    ("Сервер", "Python 3.12, FastAPI"),
    ("Данные", "PostgreSQL 16, Redis 7"),
    ("Интерфейс", "TypeScript, React; браузеры Chrome, Edge, Яндекс Браузер, Firefox"),
    ("Развёртывание", "Linux (Ubuntu, Astra Linux, РЕД ОС) + Docker Compose"),
]
for i, (h, d) in enumerate(stack):
    col, row = i % 2, i // 2
    w = 3.05
    x = LM + col * (w + 0.25)
    y = 1.85 + row * 1.75
    card(s, x, y, w, 1.55, fill=TEAL_L)
    text(s, x + 0.25, y + 0.18, w - 0.45, 1.3, [[(h, {"bold": True, "size": 16, "color": NAVY})],
                                                [(d, {"size": 14, "color": INK})]])
card(s, LM, 5.45, 6.35, 1.35, fill=GREY_L)
text(s, LM + 0.25, 5.5, 5.9, 1.25, [
    [("Служба эксплуатации ИТ: ", {"bold": True, "color": NAVY}), ("серверы, резервные копии, ключи", {})],
    [("Суперадминистратор: ", {"bold": True, "color": NAVY}), ("настройки и безопасность внутри приложения", {})],
    [("Своя команда разработки: ", {"bold": True, "color": NAVY}), ("сопровождение и обновления", {})],
], size=13, anchor=MSO_ANCHOR.MIDDLE, space_after=2)
kpis = [("≤ 1 с", "доставка правки всем участникам проекта"),
        ("≤ 2 с", "открытие проекта на 2 000 строк"),
        ("99%", "доступность в рабочее время"),
        ("15 мин / 4 ч", "допустимая потеря данных / время восстановления"),
        ("300 / 50", "пользователей в системе / одновременно")]
x0 = 7.35
for i, (v, d) in enumerate(kpis):
    y = 1.85 + i * 0.99
    text(s, x0, y, 2.35, 0.8, v, size=26, bold=True, color=TEAL, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x0 + 2.45, y, SW - LM - x0 - 2.45, 0.8, d, size=14, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    if i < len(kpis) - 1:
        line(s, x0, y + 0.9, SW - LM, y + 0.9, color=LINE, width=0.75)
footer(s)

# =====================================================================
# 24. Внедрение
s = new_slide("Внедрение начинается с первой версии и пилота на реальных проектах",
              kicker="Внедрение", notes=(
    "Как предлагается внедрять. Первая версия уже включает всё, что мы показали: вход, справочники, проекты, "
    "совместную оценку, обсуждения и вопросы заказчику, статистику, снимки, выгрузки, документы и журнал аудита. "
    "Приёмку релиза подписывают владелец продукта и служба ИБ после автотестов, проверки ИБ и двух недель "
    "приёмочного тестирования с реальными пользователями. Пилот оценивается по понятным критериям — "
    "удовлетворённость, отсутствие ожидания блокировок, прозрачность правок и простота для экспертов. "
    "Расчёт календарного срока, генерация полного КП, автоподбор норм и интеграции — кандидаты на следующие этапы."))
cols = [
    ("Первая версия", TEAL, [
        "Вход через AD или приложение, админки",
        "Проекты, команда, ставки, валюта, НДС",
        "Совместная оценка деревом",
        "Обсуждения и вопросы заказчику",
        "Статистика, снимки, сравнение",
        "Выгрузки, документы, журнал аудита",
    ]),
    ("Приёмка релиза", NAVY, [
        "Автотесты пройдены",
        "Проверка службой ИБ и сканирование OWASP ZAP",
        "Ноль открытых критичных дефектов",
        "2 недели приёмочного тестирования с реальными пользователями",
        "Подписывают владелец продукта и служба ИБ",
    ]),
    ("Критерии успеха пилота", AMBER, [
        "Удобство по опросу ≥ 4 из 5 на 10 пилотных проектах",
        "0 жалоб «не могу редактировать, занято»",
        "≥ 90% правок модератора увидены экспертом",
        "≤ 10 минут до первого заполненного листа без обучения",
    ]),
]
w = (CW - 2 * 0.3) / 3
for i, (h, col, pts) in enumerate(cols):
    x = LM + i * (w + 0.3)
    hd = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, 1.8, w, 0.6, fill=col, radius=0.2)
    label_in(hd, h, size=16)
    card(s, x, 2.5, w, 3.15, fill=TEAL_L if i < 2 else AMBER_L)
    text(s, x + 0.25, 2.65, w - 0.45, 2.95, pts, size=14, bullets=True, space_after=5)
card(s, LM, 5.85, CW, 0.95, fill=GREY_L)
text(s, LM + 0.3, 5.85, CW - 0.6, 0.95,
     [[("Следующие этапы (кандидаты): ", {"bold": True, "color": NAVY}),
       ("расчёт календарного срока по команде, генерация полного документа КП, автоподбор норм по истории проектов, "
        "интеграции с корпоративными системами, вход без пароля (SSO), мобильная версия", {})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE)
footer(s)

# =====================================================================
# 25. Итог
s = new_slide("Итог: единый инструмент делает оценку быстрой, прозрачной и защищённой", dark=True,
              kicker="Итог", notes=(
    "Подведём итог. Приложение даёт компании единый способ оценки проектов: эксперты работают одновременно, "
    "цифра для КП учитывает риск и сходится до рубля, каждая правка и каждый вопрос заказчику прозрачны, "
    "а коммерческие данные защищены. Предлагаемые шаги: одобрить пилот, выбрать пилотные проекты и команды, "
    "подготовить сервер силами эксплуатации ИТ и провести проверку ИБ, затем две недели приёмочного тестирования "
    "и пилот. Спасибо, готовы ответить на вопросы."))
take = [
    ("Быстрее", "Эксперты оценивают одновременно, никто никого не ждёт"),
    ("Точнее", "Три оценки, запас на риск, видны слабые места оценки"),
    ("Прозрачнее", "Каждая правка, вопрос и версия — с автором и историей"),
    ("Надёжнее", "Деньги только у нужных ролей, журнал аудита, внутренний контур"),
]
w = (CW - 3 * 0.3) / 4
for i, (h, d) in enumerate(take):
    x = LM + i * (w + 0.3)
    card(s, x, 1.9, w, 2.05, fill=RGBColor(0x17, 0x4E, 0x60))
    text(s, x + 0.3, 2.05, w - 0.6, 0.5, h, size=20, bold=True, color=AMBER)
    text(s, x + 0.3, 2.6, w - 0.6, 1.3, d, size=14, color=WHITE)
text(s, LM, 4.3, CW, 0.4, "Предлагаемые шаги", size=17, bold=True, color=WHITE)
nxt = ["Одобрить пилот", "Выбрать 10 пилотных проектов и команды", "Сервер — эксплуатация ИТ, проверка — служба ИБ",
       "2 недели приёмки с пользователями, затем пилот"]
w = (CW - 3 * 0.3) / 4
for i, t in enumerate(nxt):
    x = LM + i * (w + 0.3)
    circle(s, x, 4.9, 0.55, str(i + 1), fill=AMBER, color=NAVY, size=16)
    text(s, x + 0.7, 4.7, w - 0.75, 0.85, t, size=14, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
text(s, LM, 6.3, CW, 0.4, "Спасибо! Готовы ответить на вопросы", size=16, bold=True,
     color=RGBColor(0xCF, 0xE3, 0xE8))
footer(s, dark=True)

prs.core_properties.title = "Приложение совместной оценки проектов"
prs.core_properties.subject = "Предложение к внедрению"
prs.core_properties.language = "ru-RU"
prs.save(OUT)
print("saved", OUT, len(prs.slides._sldIdLst), "slides")
for i, t in enumerate(SLIDES, 1):
    print(i, t)
