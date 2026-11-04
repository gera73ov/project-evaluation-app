import re, html, sys, markdown

src, out = sys.argv[1], sys.argv[2]
md = open(src, encoding="utf-8").read()

merm = []
def keep(m):
    merm.append(m.group(1))
    return f"\n\nMERMAIDBLOCK{len(merm)-1}X\n\n"
md = re.sub(r"```mermaid\n(.*?)```", keep, md, flags=re.S)

def slug(value, sep):
    v = value.strip().lower()
    v = re.sub(r"[^\w\- ]", "", v)
    return v.replace(" ", "-")

body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc", "sane_lists"],
                         extension_configs={"toc": {"slugify": slug, "toc_depth": "2"}}, output_format="html5")
for i, m in enumerate(merm):
    body = body.replace(f"<p>MERMAIDBLOCK{i}X</p>", f'<div class="diagram"><pre class="mermaid">{html.escape(m)}</pre></div>')
body = re.sub(r"<table>", '<div class="tablewrap"><table>', body)
body = body.replace("</table>", "</table></div>")
body = re.sub(r"<pre><code", '<div class="codewrap"><pre><code', body)
body = body.replace("</code></pre>", "</code></pre></div>")
body = re.sub(r'<p><img alt="([^"]*)" src="([^"]+)"\s*/?></p>', r'<figure class="shot"><a href="\2" target="_blank" rel="noopener"><img alt="\1" src="\2" loading="lazy"></a><figcaption>\1 · нажмите, чтобы открыть в полном размере</figcaption></figure>', body)
# Highlight requirement IDs
body = re.sub(r"<strong>((?:FR|NFR|SEC|BR|TC|ARCH)-[A-Z0-9\-]+)\.</strong>", r'<strong class="rid">\1</strong>', body)

# TOC from h2
heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
heads = [h for h in heads if h[1] != "Содержание"]
toc = "\n".join(f'<li><a href="#{i}">{t}</a></li>' for i, t in heads)

tpl = open(sys.argv[3], encoding="utf-8").read()
open(out, "w", encoding="utf-8").write(tpl.replace("{{TOC}}", toc).replace("{{BODY}}", body))
print(len(heads), "sections", len(merm), "diagrams")
