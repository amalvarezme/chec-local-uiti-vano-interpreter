import mapHtml from "../assets/site/results/base_circuit_map.html?raw";

export const prerender = true;

export function GET() {
  return new Response(mapHtml, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}
