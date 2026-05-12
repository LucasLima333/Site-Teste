"""Recomendação de pontos de descarte com pontuação (zona, qualidade, proximidade)
e geração de mapa interativo a partir de banco SQLite.
"""

from __future__ import annotations

import math
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium


# ============================================================
# Configurações gerais
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "teste_descarte.db"


def _resolver_pasta_mapas() -> Path:
    """Onde salvar os HTML: portável em qualquer máquina (Windows/Linux/macOS).

    - Padrão: subpasta ``mapas`` ao lado deste arquivo (copiou o projeto = mapas vão junto).
    - Opcional: defina a variável de ambiente ``MAPAS_DESCARTE_DIR`` com um caminho
      absoluto ou relativo à pasta do script (útil para rede ou política de disco).
    """
    env = os.environ.get("MAPAS_DESCARTE_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
        return (p if p.is_absolute() else BASE_DIR / p).resolve()
    return (BASE_DIR / "mapas").resolve()


MAPAS_DIR = _resolver_pasta_mapas()

# Referência aproximada por zona (para estimar proximidade quando o usuário
# só informa a região)
ZONA_REFERENCIA: Dict[str, Tuple[float, float]] = {
    "centro": (-3.1190, -60.0217),
    "norte":  (-3.0950, -60.0150),
    "leste":  (-3.1250, -60.0180),
    "sul":    (-3.1350, -60.0280),
}

# Pesos (quanto maior a soma, melhor o ponto)
PESO_MESMA_ZONA = 100.0
PESO_NOTA = 12.0          # nota 0–5 → até 60 pontos
KM_PARA_ZERO_PROX = 8.0   # após ~8 km o bônus de proximidade zera
PESO_PROXIMIDADE_MAX = 50.0


# ============================================================
# Lógica de pontuação / recomendação
# ============================================================

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _ref_usuario(zona_norm: str) -> Optional[Tuple[float, float]]:
    return ZONA_REFERENCIA.get(zona_norm)


def _pontos_proximidade(
    lat: Any, lon: Any, ref: Optional[Tuple[float, float]]
) -> float:
    if ref is None or lat is None or lon is None:
        return 0.0
    d = haversine_km(ref[0], ref[1], float(lat), float(lon))
    # Linear: no ref (0 km) ganha PESO_PROXIMIDADE_MAX;
    # some até 0 além de KM_PARA_ZERO_PROX
    fator = max(0.0, 1.0 - d / KM_PARA_ZERO_PROX)
    return PESO_PROXIMIDADE_MAX * fator


def filtrar_pontos(
    tipo_residuo: str, zona_usuario: str, lista_pontos: List[Dict]
) -> List[Dict[str, Any]]:
    """Recebe a lista bruta de pontos e devolve a lista pontuada/ordenada."""
    tipo_norm = str(tipo_residuo).lower().strip()
    zona_norm = str(zona_usuario).lower().strip()
    ref = _ref_usuario(zona_norm)

    candidatos: List[Tuple[float, Dict[str, Any], Dict[str, float]]] = []

    for ponto in lista_pontos:
        aceitos = ponto.get("tipos_aceitos") or ponto.get("aceita") or []
        aceitos_lower = [str(a).lower() for a in aceitos]
        if tipo_norm not in aceitos_lower:
            continue

        mesma = str(ponto["zona"]).lower() == zona_norm
        pts_zona = PESO_MESMA_ZONA if mesma else 0.0

        nota = float(ponto.get("nota") if ponto.get("nota") is not None else 3.5)
        nota = max(0.0, min(5.0, nota))
        pts_nota = PESO_NOTA * nota

        pts_prox = _pontos_proximidade(ponto.get("lat"), ponto.get("lon"), ref)
        total = pts_zona + pts_nota + pts_prox

        detalhe = {
            "mesma_zona": round(pts_zona, 2),
            "qualidade": round(pts_nota, 2),
            "proximidade": round(pts_prox, 2),
        }
        candidatos.append((total, ponto, detalhe))

    candidatos.sort(key=lambda x: x[0], reverse=True)

    resultado: List[Dict[str, Any]] = []
    for total, ponto, detalhe in candidatos:
        base = dict(ponto)
        base["pontuacao"] = round(total, 2)
        base["pontuacao_detalhe"] = detalhe
        resultado.append(base)

    return resultado


# ============================================================
# Banco de dados
# ============================================================

class DatabaseError(Exception):
    pass


def conectar_banco() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"Banco não encontrado em {DB_PATH}. Execute: python criar_banco_descarte.py"
        )
    return sqlite3.connect(DB_PATH)


def buscar_tipos_por_ponto(conn: sqlite3.Connection, ponto_id: int) -> List[str]:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.codigo
        FROM ponto_aceita p
        JOIN tipos_residuo t ON t.id = p.tipo_id
        WHERE p.ponto_id = ?
        ORDER BY t.codigo
    """, (ponto_id,))
    return [row[0] for row in cursor.fetchall()]


def carregar_pontos_do_banco() -> List[Dict]:
    try:
        with conectar_banco() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, nome, endereco, zona, latitude, longitude, nota
                FROM pontos_descarte
                ORDER BY id
            """)

            pontos = []
            for pid, nome, endereco, zona, lat, lon, nota in cursor.fetchall():
                tipos = buscar_tipos_por_ponto(conn, pid)
                pontos.append({
                    "nome": nome,
                    "zona": zona,
                    "aceita": tipos,
                    "endereco": endereco or "",
                    "lat": lat,
                    "lon": lon,
                    "nota": nota,
                })
            return pontos

    except sqlite3.Error as e:
        raise DatabaseError(f"Erro ao acessar o banco: {e}") from e


def listar_regioes_do_banco() -> List[str]:
    with conectar_banco() as conn:
        rows = conn.execute(
            "SELECT DISTINCT zona FROM pontos_descarte ORDER BY zona COLLATE NOCASE"
        ).fetchall()
    return [r[0] for r in rows]


def listar_materiais_do_banco() -> List[Tuple[str, str]]:
    with conectar_banco() as conn:
        rows = conn.execute(
            "SELECT codigo, nome FROM tipos_residuo ORDER BY nome COLLATE NOCASE"
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


# ============================================================
# Interação com usuário (CLI)
# ============================================================

def _pedir_numero(mensagem: str, maximo: int) -> int:
    while True:
        raw = input(mensagem).strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= maximo:
                return n
        print(f"Digite um número entre 1 e {maximo}.")


def escolher_regiao() -> str:
    regioes = listar_regioes_do_banco()
    if not regioes:
        raise RuntimeError("Não há regiões cadastradas no banco.")
    print("\n--- Em qual região você mora? ---")
    for i, z in enumerate(regioes, 1):
        print(f"  {i}. {z}")
    n = _pedir_numero("Número da sua região: ", len(regioes))
    return regioes[n - 1]


def escolher_material() -> str:
    materiais = listar_materiais_do_banco()
    if not materiais:
        raise RuntimeError("Não há tipos de resíduo cadastrados no banco.")
    print("\n--- Qual material você quer descartar? ---")
    for i, (codigo, nome) in enumerate(materiais, 1):
        print(f"  {i}. {nome} (código: {codigo})")
    n = _pedir_numero("Número do material: ", len(materiais))
    return materiais[n - 1][0]


def recomendar_ponto(
    tipo_item: str, zona_usuario: str, *, verbose: bool = True
) -> List[Dict]:
    pontos = carregar_pontos_do_banco()
    if verbose:
        print(f"\n>> Buscando pontos para '{tipo_item}' na zona '{zona_usuario}'...")
    return filtrar_pontos(tipo_item, zona_usuario, pontos)


def imprimir_resultado(resultado: List[Dict], zona_usuario: str) -> None:
    if not resultado:
        print("Nenhum ponto encontrado.")
        return

    print("\nPontos encontrados:\n")

    for i, ponto in enumerate(resultado, start=1):
        mesma = ponto["zona"].strip().lower() == zona_usuario.strip().lower()
        if i == 1 and mesma:
            status = "* MELHOR OPCAO - sua zona"
        elif i == 1:
            status = "* MELHOR PONTUACAO - outra zona"
        else:
            status = "- Alternativa"

        det = ponto.get("pontuacao_detalhe") or {}
        pts = ponto.get("pontuacao")
        linha_pts = ""
        if pts is not None and det:
            linha_pts = (
                f"\n   Pontuacao: {pts} (zona +{det.get('mesma_zona', 0):.0f}, "
                f"qualid. +{det.get('qualidade', 0):.1f}, prox. +{det.get('proximidade', 0):.1f})"
            )

        print(f"{i}. {ponto['nome']}")
        print(f"   Endereco: {ponto['endereco']}")
        print(f"   Zona: {ponto['zona']}")
        print(f"   Status: {status}{linha_pts}\n")


# ============================================================
# Mapa
# ============================================================

def gerar_mapa(pontos: List[Dict], zona_usuario: str, arquivo="mapa.html"):
    """Salva o HTML em MAPAS_DIR (cria a pasta se não existir)."""
    caminho = Path(arquivo)
    if not caminho.is_absolute():
        MAPAS_DIR.mkdir(parents=True, exist_ok=True)
        caminho = MAPAS_DIR / caminho.name

    mapa = folium.Map(location=[-3.1190, -60.0217], zoom_start=12)
    marcadores = 0

    for i, p in enumerate(pontos):
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue

        is_top = i == 0
        cor = "red" if is_top else "blue"
        pts = p.get("pontuacao")
        popup_txt = f"{p['nome']} ({p['zona']})"
        if pts is not None:
            popup_txt += f" — pts {pts}"

        folium.Marker(
            location=[float(lat), float(lon)],
            popup=popup_txt,
            tooltip=p["nome"],
            icon=folium.Icon(color=cor),
        ).add_to(mapa)
        marcadores += 1

    mapa.save(str(caminho))
    if marcadores == 0:
        print(
            "Aviso: nenhum ponto tinha latitude/longitude no banco; "
            "o mapa foi salvo sem marcadores. Rode: python criar_banco_descarte.py"
        )
    print(f"Mapa salvo em: {caminho.resolve()}")


def _nome_arquivo_mapa(material: str, zona: str) -> str:
    def safe(s: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in s)
    return f"mapa_{safe(material)}_{safe(zona)}.html"


def _executando_streamlit() -> bool:
    import sys

    # Com `streamlit run`, o runtime já está carregado antes do script rodar.
    # Evita importar streamlit só para detectar modo (e avisos no CLI).
    return any(name.startswith("streamlit.runtime") for name in sys.modules)


def run_streamlit_ui() -> None:
    import streamlit as st
    from streamlit_folium import st_folium

    st.set_page_config(page_title="EcoDescarte - Encontre Pontos", layout="wide")

    st.title("♻️ Recomendação de Pontos de Descarte")
    st.markdown(
        "Encontre o melhor local para descartar seus resíduos com base na sua localização."
    )

    st.sidebar.header("Sua Localização e Resíduo")

    try:
        regioes = listar_regioes_do_banco()
        materiais_raw = listar_materiais_do_banco()
        materiais_dict = {nome: codigo for codigo, nome in materiais_raw}

        zona_selecionada = st.sidebar.selectbox("Onde você mora?", regioes)
        material_nome = st.sidebar.selectbox(
            "O que deseja descartar?", list(materiais_dict.keys())
        )
        material_codigo = materiais_dict[material_nome]

        if st.sidebar.button("Buscar Melhor Ponto"):
            resultado = recomendar_ponto(
                material_codigo, zona_selecionada, verbose=False
            )

            if not resultado:
                st.warning("Nenhum ponto encontrado para este material.")
            else:
                col1, col2 = st.columns([1, 1.5])

                with col1:
                    st.subheader("Melhores Opções")
                    for i, p in enumerate(resultado[:3]):
                        with st.expander(f"{i + 1}º - {p['nome']}", expanded=(i == 0)):
                            st.write(f"**Endereço:** {p['endereco']}")
                            st.write(f"**Nota:** {p['nota']} ⭐")
                            st.write(f"**Pontuação Total:** {p['pontuacao']}")

                with col2:
                    st.subheader("Mapa Interativo")
                    m = folium.Map(location=[-3.1190, -60.0217], zoom_start=12)
                    for idx, p in enumerate(resultado):
                        lat, lon = p.get("lat"), p.get("lon")
                        if lat is None or lon is None:
                            continue
                        folium.Marker(
                            [float(lat), float(lon)],
                            popup=f"{p['nome']} - {p['pontuacao']} pts",
                            tooltip=p["nome"],
                            icon=folium.Icon(color="green" if idx == 0 else "blue"),
                        ).add_to(m)

                    st_folium(m, width=700, height=500)

    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        st.info(
            "Certifique-se de que o arquivo 'teste_descarte.db' está na mesma pasta."
        )


# ============================================================
# Main
# ============================================================

def main():
    print("=== Recomendação de ponto de descarte (com mapa) ===")
    try:
        while True:
            zona = escolher_regiao()
            material = escolher_material()
            resultado = recomendar_ponto(material, zona)
            imprimir_resultado(resultado, zona)

            if resultado:
                arquivo = _nome_arquivo_mapa(material, zona)
                gerar_mapa(resultado, zona, arquivo=arquivo)

            again = input("\nDeseja fazer outra consulta? (s/n): ").strip().lower()
            if again not in ("s", "sim", "y", "yes"):
                print("Até logo.")
                break

    except FileNotFoundError as e:
        print(f"Erro: {e}")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    if _executando_streamlit():
        run_streamlit_ui()
    else:
        main()
        