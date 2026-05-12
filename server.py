"""Site EcoDescarte (Flask). Na pasta do projeto:

    pip install flask
    python server.py

Abra http://127.0.0.1:5000
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Flask, render_template, request

from Prototipo import (
    listar_materiais_do_banco,
    listar_regioes_do_banco,
    recomendar_ponto,
)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


def _materiais_lista() -> List[Dict[str, str]]:
    return [
        {"codigo": c, "nome": n} for c, n in listar_materiais_do_banco()
    ]


def _markers_para_mapa(resultado: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, p in enumerate(resultado):
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        out.append(
            {
                "lat": float(lat),
                "lng": float(lon),
                "nome": str(p.get("nome", "")),
                "pontuacao": p.get("pontuacao"),
                "destaque": idx == 0,
            }
        )
    return out


@app.route("/", methods=["GET", "POST"])
def index():
    erro: str | None = None
    resultado: List[Dict[str, Any]] | None = None
    markers: List[Dict[str, Any]] = []
    regioes: List[str] = []
    materiais: List[Dict[str, str]] = []

    try:
        regioes = listar_regioes_do_banco()
        materiais = _materiais_lista()
    except Exception as e:
        erro = f"Erro ao acessar o banco: {e}"
        return render_template(
            "index.html",
            erro=erro,
            regioes=[],
            materiais=[],
            zona_selecionada="",
            material_codigo="",
            resultado=None,
            markers=[],
        )

    zona_selecionada = request.form.get("zona") or request.args.get("zona") or ""
    material_codigo = request.form.get("material") or request.args.get("material") or ""

    if not zona_selecionada and regioes:
        zona_selecionada = regioes[0]
    if not material_codigo and materiais:
        material_codigo = materiais[0]["codigo"]

    if request.method == "POST":
        if not material_codigo:
            erro = "Selecione um tipo de resíduo."
        elif not zona_selecionada:
            erro = "Selecione sua região."
        else:
            resultado = recomendar_ponto(
                material_codigo, zona_selecionada, verbose=False
            )
            if not resultado:
                erro = "Nenhum ponto encontrado para este material nesta busca."
            else:
                markers = _markers_para_mapa(resultado)

    return render_template(
        "index.html",
        erro=erro,
        regioes=regioes,
        materiais=materiais,
        zona_selecionada=zona_selecionada,
        material_codigo=material_codigo,
        resultado=resultado,
        markers=markers,
    )


if __name__ == "__main__":
    # Desenvolvimento local; em produção use um servidor WSGI (ex.: waitress, gunicorn).
    app.run(host="127.0.0.1", port=5000, debug=True)
