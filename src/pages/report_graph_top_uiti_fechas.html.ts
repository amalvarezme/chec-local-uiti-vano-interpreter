import graphHtml from "../assets/site/results/report_graph_top_uiti_fechas.html?raw";

export const prerender = true;

export function GET() {
  return new Response(graphHtml, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}
