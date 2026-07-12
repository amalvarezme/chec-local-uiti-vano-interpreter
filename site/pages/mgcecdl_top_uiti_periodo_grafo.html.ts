import grafoHtml from "../assets/site/results/mgcecdl_top_uiti_periodo_grafo.html?raw";

export const prerender = true;

export function GET() {
  return new Response(grafoHtml, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}
