import { proxyToBackend } from "@/lib/server/backend-proxy";

const ID = "[0-9a-fA-F-]{36}";
const GET_ROUTES: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
  [/^health$/, () => "/health"],
  [/^model\/health$/, () => "/model/health"],
  [/^approvals$/, () => "/approvals"],
  [new RegExp(`^runs\/(${ID})$`), (match) => `/runs/${match[1]}`],
  [new RegExp(`^runs\/(${ID})\/audit$`), (match) => `/runs/${match[1]}/audit`],
  [new RegExp(`^audit\/verify\/(${ID})$`), (match) => `/audit/verify/${match[1]}`],
];
const POST_ROUTES: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
  [/^runs$/, () => "/runs"],
  [new RegExp(`^runs\/(${ID})\/execute$`), (match) => `/runs/${match[1]}/execute`],
  [new RegExp(`^approvals\/(${ID})\/(approve|reject)$`), (match) => `/approvals/${match[1]}/${match[2]}`],
];

type RouteContext = { params: Promise<{ segments: string[] }> };

async function route(
  request: Request,
  context: RouteContext,
  allowed: Array<[RegExp, (match: RegExpMatchArray) => string]>,
): Promise<Response> {
  const { segments } = await context.params;
  const path = segments.join("/");
  for (const [pattern, build] of allowed) {
    const match = path.match(pattern);
    if (match) {
      let backendPath = build(match);
      if (path === "approvals") {
        const runId = new URL(request.url).searchParams.get("run_id");
        if (runId) {
          if (!new RegExp(`^${ID}$`).test(runId)) {
            return Response.json({ code: "invalid_run_id", message: "The run ID is invalid." }, { status: 400 });
          }
          backendPath += `?run_id=${encodeURIComponent(runId)}`;
        }
      }
      return proxyToBackend(request, backendPath);
    }
  }
  return Response.json(
    { code: "proxy_route_not_allowed", message: "This local proxy route is not allowed." },
    { status: 404 },
  );
}

export function GET(request: Request, context: RouteContext): Promise<Response> {
  return route(request, context, GET_ROUTES);
}

export function POST(request: Request, context: RouteContext): Promise<Response> {
  return route(request, context, POST_ROUTES);
}
