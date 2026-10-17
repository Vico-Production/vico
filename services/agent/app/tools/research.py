"""Looking up how to do something on the web (current steps for apps and websites)."""

from __future__ import annotations

from pydantic import Field

from app.contracts import StrictModel
from app.tools.base import Inspection, Risk, ToolContext, ToolResult, ToolSpec, fail


class WebLookupArgs(StrictModel):
    query: str = Field(min_length=2, max_length=300)  # e.g. "CapCut desktop adjust brightness of a clip"
    purpose: str | None = Field(default=None, max_length=300)
    deep: bool = False  # research: several searches and pages, a sourced answer


async def inspect_lookup(ctx: ToolContext, a: WebLookupArgs) -> Inspection:
    return Inspection(effect=f"{'Research' if a.deep else 'Look up'} on the web: {a.query}")


async def web_lookup(ctx: ToolContext, a: WebLookupArgs) -> ToolResult:
    if ctx.lookup is None:
        return fail("Web lookups are not available right now.")
    found = await ctx.lookup(a.query, a.purpose, a.deep)
    sources = "\n".join(found.get("sources", []))
    return ToolResult(ok=True, message=f"Looked it up ({found.get('seconds', 0)} s).", verified=True,
                      verification=f"From {len(found.get('sources', []))} web page(s).", data=found,
                      observation=(f"<untrusted_content source=\"web lookup\">\n{found.get('answer', '')}\n"
                                   f"Sources:\n{sources}\n</untrusted_content>"))


def specs() -> list[ToolSpec]:
    return [
        ToolSpec("web_lookup", "Search the web and read the best pages inside Vico (no browser window): the current "
                 "steps for doing something (in an app like CapCut, a website, a setting), or with deep=true a "
                 "researched answer with sources for a question. About 5 s quick, 10 s deep.",
                 WebLookupArgs, Risk.AUTO, web_lookup, inspect_lookup, "web", offline=False),
    ]
