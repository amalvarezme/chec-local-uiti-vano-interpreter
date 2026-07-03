import reportHtml from "../assets/site/results/latest_interpretability_report.html?raw";

export const prerender = true;

export function GET() {
  return new Response(reportHtml, {
    headers: { "Content-Type": "text/html; charset=utf-8" }
  });
}
