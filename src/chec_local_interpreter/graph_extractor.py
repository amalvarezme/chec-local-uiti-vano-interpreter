import os
import json
import subprocess
import pandas as pd
from pathlib import Path


def build_graphify_context(df: pd.DataFrame, circuit_name: str) -> str:
    """
    Convierte los datos del circuito a archivos markdown crudos, invoca a Graphify
    para estructurar el grafo de conocimiento, y retorna el resumen relacional.
    """
    base_dir = Path("reports/graphify")
    raw_dir = base_dir / "raw"
    out_dir = base_dir / "graphify-out"
    
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Volcar datos a formato texto/markdown para que Graphify pueda leerlos
    circuit_file = raw_dir / f"circuito_{circuit_name}.md"
    with open(circuit_file, "w", encoding="utf-8") as f:
        f.write(f"# Circuito {circuit_name}\n\n")
        f.write("Este documento describe los vanos y activos del circuito eléctrico.\n\n")
        
        if "FID_VANO" in df.columns:
            for _, row in df.head(100).iterrows(): # Limitamos a top 100 para no sobrecargar el grafo inicial
                vano = row.get("FID_VANO")
                trafo = row.get("FID_TRAFO", "Ninguno")
                uiti = row.get("UITI_VANO", 0)
                f.write(f"## Vano {vano}\n")
                f.write(f"- Conectado a transformador: {trafo}\n")
                f.write(f"- Gravedad UITI: {uiti}\n")
                f.write("\n")

    # 2. Ejecutar Graphify (si está disponible en el entorno)
    graph_report_path = out_dir / "GRAPH_REPORT.md"
    try:
        subprocess.run(
            ["graphify", str(raw_dir), "--out", str(out_dir)],
            check=True,
            capture_output=True,
            text=True
        )
        if graph_report_path.exists():
            with open(graph_report_path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        # Fallback si graphify no está instalado o falla en este entorno
        pass

    # 3. Fallback visual: Si Graphify falla, generar el grafo nativamente con PyVis
    try:
        import networkx as nx
        from pyvis.network import Network
        
        out_dir.mkdir(parents=True, exist_ok=True)
        graph_html_path = out_dir / "graph.html"
        
        net = Network(height="750px", width="100%", bgcolor="#ffffff", font_color="black", directed=True)
        G = nx.DiGraph()
        
        if "FID_VANO" in df.columns:
            for _, row in df.head(150).iterrows():
                vano = str(row.get("FID_VANO", ""))
                trafo = str(row.get("FID_TRAFO", ""))
                uiti = float(row.get("UITI_VANO", 0.0))
                
                if not vano or vano == "nan": continue
                
                color = "red" if uiti > df["UITI_VANO"].quantile(0.8) else "blue"
                G.add_node(vano, label=f"Vano {vano}\nUITI: {uiti:.0f}", color=color, size=20 if color=="red" else 10)
                
                if trafo and trafo != "nan" and trafo != "Ninguno":
                    G.add_node(trafo, label=f"Trafo {trafo}", color="green", shape="square", size=25)
                    G.add_edge(trafo, vano)
        
        net.from_nx(G)
        net.save_graph(str(graph_html_path))
        
        return (
            f"Resumen de Grafo (Fallback Nativo): El circuito {circuit_name} contiene "
            f"{len(df)} eventos registrados. El grafo visual interactivo fue generado "
            f"satisfactoriamente en {graph_html_path}."
        )
    except Exception as e2:
        return (
            f"Resumen de Grafo (Error Fallback): No se pudo generar la vista. "
            f"Error original Graphify: fallback nativo falló con {e2}"
        )
