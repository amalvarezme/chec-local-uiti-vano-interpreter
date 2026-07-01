import criticalPointsHtml from "../assets/site/results/base_critical_points.html?raw";

export const prerender = true;

export function GET() {
  return new Response(criticalPointsHtml, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}
