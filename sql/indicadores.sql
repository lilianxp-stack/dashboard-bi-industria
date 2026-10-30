-- =====================================================================
-- Indicadores comerciais e de produção — indústria metalúrgica (dados fictícios)
-- Banco: dados/industria.db (SQLite). Cada consulta tem um nome no
-- comentário "-- name:" e é lida pelo script src/dashboard.py
-- =====================================================================

-- name: kpis_ano
-- Faturamento, margem, ticket médio e entregas no prazo por ano
WITH vendas AS (
    SELECT p.id_pedido,
           strftime('%Y', p.data_pedido)                      AS ano,
           SUM(i.quantidade * i.preco_unitario)               AS receita,
           SUM(i.quantidade * (i.preco_unitario - i.custo_unitario)) AS margem,
           MAX(CASE WHEN p.data_entrega <= p.data_prevista_entrega THEN 1 ELSE 0 END) AS no_prazo
    FROM fato_pedido p
    JOIN fato_item_pedido i ON i.id_pedido = p.id_pedido
    GROUP BY p.id_pedido
)
SELECT ano,
       ROUND(SUM(receita), 2)                       AS faturamento,
       ROUND(100.0 * SUM(margem) / SUM(receita), 1) AS margem_pct,
       COUNT(*)                                     AS pedidos,
       ROUND(SUM(receita) / COUNT(*), 2)            AS ticket_medio,
       ROUND(100.0 * AVG(no_prazo), 1)              AS entregas_no_prazo_pct
FROM vendas
GROUP BY ano
ORDER BY ano;

-- name: faturamento_mensal
-- Faturamento e margem por mês, com variação sobre o mesmo mês do ano anterior
WITH mensal AS (
    SELECT strftime('%Y-%m', p.data_pedido) AS ano_mes,
           SUM(i.quantidade * i.preco_unitario) AS faturamento,
           SUM(i.quantidade * (i.preco_unitario - i.custo_unitario)) AS margem
    FROM fato_pedido p
    JOIN fato_item_pedido i ON i.id_pedido = p.id_pedido
    GROUP BY 1
)
SELECT ano_mes,
       ROUND(faturamento, 2) AS faturamento,
       ROUND(100.0 * margem / faturamento, 1) AS margem_pct,
       ROUND(100.0 * (faturamento / LAG(faturamento, 12) OVER (ORDER BY ano_mes) - 1), 1) AS var_ano_anterior_pct
FROM mensal
ORDER BY ano_mes;

-- name: margem_por_linha
-- Receita e margem por linha de produto em cada ano (mostra o efeito do aumento de custo em 2025)
SELECT pr.linha,
       strftime('%Y', p.data_pedido) AS ano,
       ROUND(SUM(i.quantidade * i.preco_unitario), 2) AS faturamento,
       ROUND(100.0 * SUM(i.quantidade * (i.preco_unitario - i.custo_unitario))
             / SUM(i.quantidade * i.preco_unitario), 1) AS margem_pct
FROM fato_item_pedido i
JOIN fato_pedido p  ON p.id_pedido  = i.id_pedido
JOIN dim_produto pr ON pr.id_produto = i.id_produto
GROUP BY pr.linha, ano
ORDER BY pr.linha, ano;

-- name: curva_abc_clientes
-- Classificação ABC: A = clientes que somam 80% do faturamento, B = até 95%, C = restante
WITH por_cliente AS (
    SELECT c.cliente, c.segmento, c.uf,
           SUM(i.quantidade * i.preco_unitario) AS faturamento
    FROM fato_item_pedido i
    JOIN fato_pedido p ON p.id_pedido = i.id_pedido
    JOIN dim_cliente c ON c.id_cliente = p.id_cliente
    GROUP BY c.id_cliente
),
acumulado AS (
    SELECT *,
           SUM(faturamento) OVER (ORDER BY faturamento DESC) / SUM(faturamento) OVER () AS pct_acumulado,
           ROW_NUMBER() OVER (ORDER BY faturamento DESC) AS ranking
    FROM por_cliente
)
SELECT ranking, cliente, segmento, uf,
       ROUND(faturamento, 2) AS faturamento,
       ROUND(100 * pct_acumulado, 1) AS pct_acumulado,
       CASE WHEN pct_acumulado <= 0.80 THEN 'A'
            WHEN pct_acumulado <= 0.95 THEN 'B'
            ELSE 'C' END AS classe
FROM acumulado
ORDER BY ranking;

-- name: faturamento_por_uf
SELECT c.uf,
       ROUND(SUM(i.quantidade * i.preco_unitario), 2) AS faturamento,
       COUNT(DISTINCT c.id_cliente) AS clientes
FROM fato_item_pedido i
JOIN fato_pedido p ON p.id_pedido = i.id_pedido
JOIN dim_cliente c ON c.id_cliente = p.id_cliente
GROUP BY c.uf
ORDER BY faturamento DESC;

-- name: producao_por_maquina
-- Refugo e eficiência (tempo padrão / tempo real) por máquina
SELECT o.maquina,
       pr.linha,
       COUNT(*) AS ordens,
       SUM(o.qtd_planejada) AS qtd_produzida,
       ROUND(100.0 * SUM(o.qtd_refugo) / SUM(o.qtd_planejada), 2) AS refugo_pct,
       ROUND(100.0 * SUM(o.tempo_planejado_min) / SUM(o.tempo_real_min), 1) AS eficiencia_pct,
       ROUND(SUM(o.qtd_refugo * pr.custo_unitario), 2) AS custo_refugo
FROM fato_ordem_producao o
JOIN dim_produto pr ON pr.id_produto = o.id_produto
GROUP BY o.maquina, pr.linha
ORDER BY refugo_pct DESC;

-- name: atraso_por_vendedor
SELECT p.vendedor,
       COUNT(*) AS pedidos,
       ROUND(100.0 * AVG(CASE WHEN p.data_entrega <= p.data_prevista_entrega THEN 1 ELSE 0 END), 1) AS no_prazo_pct,
       ROUND(AVG(MAX(julianday(p.data_entrega) - julianday(p.data_prevista_entrega), 0)), 2) AS atraso_medio_dias
FROM fato_pedido p
GROUP BY p.vendedor
ORDER BY no_prazo_pct;
