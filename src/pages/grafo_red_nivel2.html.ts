import grafoHtml from "../assets/site/results/grafo_red_nivel2.html?raw";

export const prerender = true;

export function GET() {
  return new Response(grafoHtml, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}
