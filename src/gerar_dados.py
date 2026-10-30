"""
Gera uma base FICTÍCIA de uma indústria metalúrgica, no formato de dados que
sai de um ERP (clientes, produtos, pedidos de venda e ordens de produção),
e grava em CSV (para o Power BI) e em um banco SQLite (para as consultas SQL).

Os dados são simulados, mas com comportamentos realistas: sazonalidade,
crescimento, clientes concentrados (curva ABC), atrasos de entrega e refugo
de produção que varia por linha e por máquina.

Como rodar (a partir da pasta do projeto):
    python src/gerar_dados.py
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
DADOS.mkdir(exist_ok=True)
rng = np.random.default_rng(7)

INICIO, FIM = "2024-01-01", "2025-12-31"

# ------------------------------------------------------------------ Produtos
linhas = {
    "Estruturas metálicas": (["Viga", "Coluna", "Treliça", "Perfil U", "Perfil I"], 900, 0.24),
    "Peças usinadas":       (["Eixo", "Flange", "Bucha", "Engrenagem", "Polia"], 220, 0.38),
    "Caldeiraria":          (["Tanque", "Silo", "Tubulação", "Duto", "Reservatório"], 2600, 0.30),
    "Componentes agrícolas": (["Lâmina", "Disco", "Suporte", "Haste", "Garra"], 140, 0.33),
}
produtos = []
pid = 1
for linha, (nomes, preco_base, margem) in linhas.items():
    for nome in nomes:
        for variante in ["P", "M", "G"]:
            fator = {"P": 0.6, "M": 1.0, "G": 1.7}[variante]
            preco = round(preco_base * fator * rng.uniform(0.85, 1.15), 2)
            produtos.append({
                "id_produto": pid, "produto": f"{nome} {variante}", "linha": linha,
                "preco_tabela": preco,
                "custo_unitario": round(preco * (1 - margem * rng.uniform(0.8, 1.2)), 2),
                "tempo_padrao_min": round(rng.uniform(15, 90) * fator, 1),
            })
            pid += 1
produtos = pd.DataFrame(produtos)

# ------------------------------------------------------------------ Clientes
estados = ["MG", "SP", "RJ", "PR", "GO", "SC", "BA", "ES", "RS", "MT"]
peso_uf = np.array([30, 22, 10, 8, 7, 6, 5, 5, 4, 3], dtype=float)
segmentos = ["Construção civil", "Agronegócio", "Mineração", "Alimentos", "Energia", "Automotivo"]
n_cli = 120
clientes = pd.DataFrame({
    "id_cliente": range(1, n_cli + 1),
    "cliente": [f"Cliente {i:03d}" for i in range(1, n_cli + 1)],
    "uf": rng.choice(estados, n_cli, p=peso_uf / peso_uf.sum()),
    "segmento": rng.choice(segmentos, n_cli),
})
# poucos clientes compram muito (distribuição log-normal, gera uma curva ABC realista)
peso_cliente = rng.lognormal(0, 1.3, n_cli)
peso_cliente /= peso_cliente.sum()

afinidade = {  # que linha cada segmento compra mais
    "Construção civil": "Estruturas metálicas", "Agronegócio": "Componentes agrícolas",
    "Mineração": "Caldeiraria", "Alimentos": "Caldeiraria", "Energia": "Estruturas metálicas",
    "Automotivo": "Peças usinadas",
}

# ------------------------------------------------------------------ Pedidos de venda
datas = pd.date_range(INICIO, FIM, freq="D")
datas = datas[datas.dayofweek < 5]  # só dias úteis
vendedores = ["Ana Souza", "Bruno Lima", "Carla Dias", "Diego Rocha", "Elisa Prado"]
pedidos, itens = [], []
id_pedido = 1
for d in datas:
    sazonal = 1 + 0.25 * np.sin(2 * np.pi * (d.month - 3) / 12)   # pico no meio do ano
    crescimento = 1 + 0.18 * (d - datas[0]).days / 730
    for _ in range(rng.poisson(6 * sazonal * crescimento)):
        cli = rng.choice(clientes.index, p=peso_cliente)
        segmento = clientes.loc[cli, "segmento"]
        prazo = int(rng.choice([7, 10, 15, 20, 30]))
        vendedor = rng.choice(vendedores)
        # prazos curtos atrasam mais; um vendedor costuma prometer prazos apertados
        p_atraso = 0.10 + (0.10 if prazo <= 10 else 0) + (0.12 if vendedor == "Diego Rocha" else 0)
        desvio = int(rng.integers(1, 9)) if rng.random() < p_atraso else -int(rng.integers(0, 3))
        pedidos.append({
            "id_pedido": id_pedido, "data_pedido": d.date(),
            "id_cliente": int(clientes.loc[cli, "id_cliente"]),
            "vendedor": vendedor,
            "data_prevista_entrega": (d + pd.Timedelta(days=prazo)).date(),
            "data_entrega": (d + pd.Timedelta(days=prazo + desvio)).date(),
        })
        n_itens = rng.integers(1, 5)
        linha_pref = afinidade[segmento]
        p_prod = np.where(produtos["linha"] == linha_pref, 4.0, 1.0)
        p_prod /= p_prod.sum()
        for pid in rng.choice(produtos["id_produto"], n_itens, replace=False, p=p_prod):
            prod = produtos.loc[produtos["id_produto"] == pid].iloc[0]
            qtd = int(max(1, rng.lognormal(2.2, 0.8) * (300 / max(prod["preco_tabela"], 50)) ** 0.5))
            reajuste = 1.06 if d.year == 2025 else 1.0
            desconto = rng.choice([0, 0, 0.03, 0.05, 0.08, 0.12])
            itens.append({
                "id_pedido": id_pedido, "id_produto": int(pid), "quantidade": qtd,
                "preco_unitario": round(prod["preco_tabela"] * reajuste * (1 - desconto), 2),
                "custo_unitario": round(prod["custo_unitario"] * (1.08 if d.year == 2025 else 1.0), 2),
                "desconto_pct": desconto,
            })
        id_pedido += 1
pedidos = pd.DataFrame(pedidos)
itens = pd.DataFrame(itens)

# ------------------------------------------------------------------ Ordens de produção
maquinas = {"Estruturas metálicas": ["Corte Plasma 01", "Solda 02", "Dobradeira 01"],
            "Peças usinadas": ["Torno CNC 01", "Torno CNC 02", "Centro Usinagem 01"],
            "Caldeiraria": ["Calandra 01", "Solda 03"],
            "Componentes agrícolas": ["Prensa 01", "Prensa 02"]}
refugo_base = {"Torno CNC 02": 0.055, "Prensa 02": 0.045}   # máquinas com mais problema
ordens = []
for i, it in enumerate(itens.merge(pedidos[["id_pedido", "data_pedido"]]).itertuples(), start=1):
    prod = produtos.loc[produtos["id_produto"] == it.id_produto].iloc[0]
    maq = rng.choice(maquinas[prod["linha"]])
    qtd_prod = it.quantidade + int(np.ceil(it.quantidade * 0.03))
    taxa_ref = np.clip(rng.normal(refugo_base.get(maq, 0.02), 0.01), 0, 0.2)
    inicio = pd.Timestamp(it.data_pedido) + pd.Timedelta(days=int(rng.integers(1, 4)))
    tempo_plan = prod["tempo_padrao_min"] * qtd_prod
    ordens.append({
        "id_ordem": i, "id_pedido": it.id_pedido, "id_produto": it.id_produto,
        "maquina": maq, "data_inicio": inicio.date(),
        "qtd_planejada": qtd_prod,
        "qtd_refugo": int(rng.binomial(qtd_prod, taxa_ref)),
        "tempo_planejado_min": round(tempo_plan, 1),
        "tempo_real_min": round(tempo_plan * rng.lognormal(0.05, 0.12), 1),
    })
ordens = pd.DataFrame(ordens)
ordens["qtd_boa"] = ordens["qtd_planejada"] - ordens["qtd_refugo"]

# ------------------------------------------------------------------ Calendário
cal = pd.DataFrame({"data": pd.date_range(INICIO, FIM, freq="D")})
cal["ano"] = cal["data"].dt.year
cal["mes"] = cal["data"].dt.month
cal["ano_mes"] = cal["data"].dt.strftime("%Y-%m")
cal["trimestre"] = "T" + cal["data"].dt.quarter.astype(str)
cal["dia_util"] = (cal["data"].dt.dayofweek < 5).astype(int)
cal["data"] = cal["data"].dt.date

# ------------------------------------------------------------------ Gravação
tabelas = {"dim_produto": produtos, "dim_cliente": clientes, "dim_calendario": cal,
           "fato_pedido": pedidos, "fato_item_pedido": itens, "fato_ordem_producao": ordens}
with sqlite3.connect(DADOS / "industria.db") as con:
    for nome, df in tabelas.items():
        df.to_csv(DADOS / f"{nome}.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
        df.to_sql(nome, con, if_exists="replace", index=False)
        print(f"{nome:22s} {len(df):>7,} linhas")
