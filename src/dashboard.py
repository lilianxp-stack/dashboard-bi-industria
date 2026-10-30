"""
Executa as consultas de sql/indicadores.sql no banco SQLite e gera um
dashboard interativo em HTML (dashboard/index.html), que pode ser publicado
no GitHub Pages. O mesmo modelo de dados é usado no Power BI (ver README).

Como rodar (a partir da pasta do projeto):
    python src/gerar_dados.py     # cria a base, se ainda não existir
    python src/dashboard.py
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

BASE = Path(__file__).resolve().parent.parent
AZUL, LARANJA, CINZA, VERDE, VERMELHO = "#1f5f99", "#e07b39", "#9aa5b1", "#2e8b57", "#c0392b"


def carregar_consultas() -> dict:
    texto = (BASE / "sql" / "indicadores.sql").read_text(encoding="utf-8")
    partes = re.split(r"^-- name:\s*(\w+)\s*$", texto, flags=re.M)
    return {partes[i]: partes[i + 1].strip() for i in range(1, len(partes), 2)}


def brl(v):
    s = f"{v:,.0f}".replace(",", ".")
    return f"R$ {s}"


def layout(fig, titulo):
    fig.update_layout(title=dict(text=titulo, font=dict(size=15)), template="plotly_white",
                      margin=dict(l=40, r=20, t=50, b=40), height=360,
                      legend=dict(orientation="h", y=-0.2), font=dict(family="Inter, Arial", size=12))
    return fig


def main():
    consultas = carregar_consultas()
    with sqlite3.connect(BASE / "dados" / "industria.db") as con:
        r = {nome: pd.read_sql_query(sql, con) for nome, sql in consultas.items()}

    for nome, df in r.items():
        print(f"\n=== {nome} ===\n{df.head(8).to_string(index=False)}")

    k = r["kpis_ano"].set_index("ano")
    a, b = k.loc["2024"], k.loc["2025"]

    def var(campo, pp=False):
        d = b[campo] - a[campo] if pp else 100 * (b[campo] / a[campo] - 1)
        cor = VERDE if d >= 0 else VERMELHO
        txt = f'{d:+.1f}'.replace(".", ",")
        return f'<span style="color:{cor}">{txt}{" p.p." if pp else "%"} vs 2024</span>'

    cards = [
        ("Faturamento 2025", brl(b["faturamento"]), var("faturamento")),
        ("Margem bruta 2025", f'{b["margem_pct"]:.1f}%'.replace(".", ","), var("margem_pct", pp=True)),
        ("Ticket médio 2025", brl(b["ticket_medio"]), var("ticket_medio")),
        ("Entregas no prazo 2025", f'{b["entregas_no_prazo_pct"]:.1f}%'.replace(".", ","), var("entregas_no_prazo_pct", pp=True)),
    ]

    graficos = []

    fm = r["faturamento_mensal"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=fm["ano_mes"], y=fm["faturamento"], name="Faturamento", marker_color=AZUL)
    fig.add_scatter(x=fm["ano_mes"], y=fm["margem_pct"], name="Margem %", mode="lines+markers",
                    line=dict(color=LARANJA), secondary_y=True)
    fig.update_yaxes(title_text="R$", secondary_y=False)
    fig.update_yaxes(title_text="Margem %", secondary_y=True, range=[0, 40], dtick=10, showgrid=False)
    graficos.append(layout(fig, "Faturamento e margem mensal"))

    ml = r["margem_por_linha"].pivot(index="linha", columns="ano", values="margem_pct").reset_index()
    fig = go.Figure()
    fig.add_bar(x=ml["linha"], y=ml["2024"], name="2024", marker_color=CINZA, text=ml["2024"], textposition="outside")
    fig.add_bar(x=ml["linha"], y=ml["2025"], name="2025", marker_color=AZUL, text=ml["2025"], textposition="outside")
    fig.update_yaxes(title_text="Margem %", range=[0, 45])
    graficos.append(layout(fig, "Margem bruta por linha de produto"))

    abc = r["curva_abc_clientes"]
    cores = abc["classe"].map({"A": AZUL, "B": LARANJA, "C": CINZA})
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=abc["ranking"], y=abc["faturamento"], marker_color=cores, name="Faturamento por cliente",
                hovertext=abc["cliente"] + " · classe " + abc["classe"])
    fig.add_scatter(x=abc["ranking"], y=abc["pct_acumulado"], name="% acumulado",
                    line=dict(color="black"), secondary_y=True)
    fig.update_yaxes(title_text="% acumulado", range=[0, 105], dtick=20, secondary_y=True, showgrid=False)
    fig.update_xaxes(title_text="Clientes (ordenados por faturamento)")
    n_a = (abc["classe"] == "A").sum()
    graficos.append(layout(fig, f"Curva ABC: {n_a} de {len(abc)} clientes geram 80% do faturamento"))

    uf = r["faturamento_por_uf"]
    fig = go.Figure(go.Bar(x=uf["faturamento"], y=uf["uf"], orientation="h", marker_color=AZUL))
    fig.update_yaxes(autorange="reversed")
    graficos.append(layout(fig, "Faturamento por estado"))

    pm = r["producao_por_maquina"].sort_values("refugo_pct")
    fig = go.Figure(go.Bar(x=pm["refugo_pct"], y=pm["maquina"], orientation="h",
                           marker_color=[VERMELHO if v > 3.5 else AZUL for v in pm["refugo_pct"]],
                           text=[f"{v:.1f}% · {brl(c)}" for v, c in zip(pm["refugo_pct"], pm["custo_refugo"])],
                           textposition="outside"))
    fig.update_xaxes(title_text="% de refugo", range=[0, pm["refugo_pct"].max() * 1.6])
    graficos.append(layout(fig, "Refugo por máquina (rótulo: % e custo do refugo)"))

    av = r["atraso_por_vendedor"]
    fig = go.Figure(go.Bar(x=av["vendedor"], y=av["no_prazo_pct"], marker_color=AZUL,
                           text=av["no_prazo_pct"], textposition="outside"))
    fig.update_yaxes(title_text="% entregas no prazo", range=[0, 100])
    graficos.append(layout(fig, "Entregas no prazo por vendedor"))

    divs = [g.to_html(full_html=False, include_plotlyjs=(True if i == 0 else False),
                      config={"displaylogo": False, "responsive": True}, default_width="100%")
            for i, g in enumerate(graficos)]
    cards_html = "".join(f'<div class="card"><div class="rot">{t}</div><div class="val">{v}</div>'
                         f'<div class="var">{d}</div></div>' for t, v, d in cards)
    graficos_html = "".join(f'<div class="painel">{d}</div>' for d in divs)

    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard Comercial e Produção</title>
<style>
 body {{ font-family: Inter, Arial, sans-serif; background:#f4f6f9; margin:0; color:#1d2733; }}
 header {{ background:{AZUL}; color:white; padding:20px 32px; }}
 header h1 {{ margin:0; font-size:22px; }} header p {{ margin:4px 0 0; opacity:.85; font-size:13px; }}
 main {{ max-width:1300px; margin:auto; padding:24px 16px; }}
 .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:16px; }}
 .card {{ background:white; border-radius:10px; padding:16px 20px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
 .rot {{ font-size:13px; color:#5b6875; }} .val {{ font-size:26px; font-weight:700; margin:6px 0; }} .var {{ font-size:13px; }}
 .grade {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,560px),1fr)); gap:16px; }}
 .painel {{ background:white; border-radius:10px; padding:8px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
 footer {{ text-align:center; font-size:12px; color:#5b6875; padding:16px; }}
</style></head><body>
<header><h1>Indústria Metalúrgica — Painel Comercial e de Produção</h1>
<p>Pedidos de jan/2024 a dez/2025 · dados fictícios gerados para fins de portfólio</p></header>
<main><div class="cards">{cards_html}</div><div class="grade">{graficos_html}</div></main>
<footer>Fonte: base simulada de ERP (SQLite) · consultas em sql/indicadores.sql</footer>
<script>window.addEventListener("load", () =>
  document.querySelectorAll(".js-plotly-plot").forEach(d => Plotly.Plots.resize(d)));</script>
</body></html>"""
    destino = BASE / "dashboard" / "index.html"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(html, encoding="utf-8")
    print(f"\nDashboard salvo em {destino}")


if __name__ == "__main__":
    main()
