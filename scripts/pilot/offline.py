"""Personal tool offline.py - full throttle, allow external assets and network.

Previously localized only 2 CDN scripts. Now we support:
- Latest hyperframes and gsap from node_modules
- Allow external assets (images, fonts, audio, video) via network - so we DON'T strip them
- Still localize known CDN scripts to local files for offline fallback, but keep external URLs if they are not the pinned ones
- Inject variables support
"""
from pathlib import Path
import re
import json


def localize(html):
    # Map of known CDN URLs to local files - keep for backward compat and offline fallback
    replacements = {
        "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js": "gsap.min.js",
        "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js": "gsap.min.js",
        "https://cdn.jsdelivr.net/npm/gsap/dist/gsap.min.js": "gsap.min.js",
        "https://cdn.jsdelivr.net/npm/@hyperframes/core/dist/hyperframe.runtime.iife.js": "hyperframe.runtime.iife.js",
        "https://cdn.jsdelivr.net/npm/@hyperframes/core@0.8.58/dist/hyperframe.runtime.iife.js": "hyperframe.runtime.iife.js",
        "https://cdn.jsdelivr.net/npm/@hyperframes/core@latest/dist/hyperframe.runtime.iife.js": "hyperframe.runtime.iife.js",
    }

    # Only rewrite exact, quoted src attributes for known runtimes. Leave all other external URLs intact (full throttle allows network).
    def replace(match):
        quote = match.group(1)
        url = match.group(2)
        local = replacements.get(url)
        if local:
            return f'src={quote}{local}{quote}'
        # Keep original URL for external assets (images, fonts, audio, etc.) - network allowed now
        return match.group(0)

    return re.sub(r'\bsrc\s*=\s*([\x22\x27])([^\x22\x27]+)\1', replace, html, flags=re.I)


def inject_variables(html, variables):
    """Inject variables override into HTML if variables provided."""
    if not variables:
        return html
    # Create a script that overrides hyperframes getVariables
    vars_json = json.dumps(variables)
    injection = f"""
<script id="hf-personal-vars-injection">
(function() {{
  var injected = {vars_json};
  try {{
    window.__hyperframes = window.__hyperframes || {{}};
    var origGetVars = window.__hyperframes.getVariables;
    window.__hyperframes.getVariables = function() {{
      var base = {{}};
      try {{
        if (typeof origGetVars === 'function') base = origGetVars() || {{}};
      }} catch(e) {{}}
      return Object.assign({{}}, base, injected);
    }};
  }} catch(e) {{ console.warn('vars injection failed', e); }}
}})();
</script>
"""
    # Inject before </head> or after <body> start
    if "</head>" in html:
        return html.replace("</head>", injection + "</head>", 1)
    elif "<body" in html:
        # insert after body tag
        return re.sub(r"(<body[^>]*>)", r"\1" + injection, html, count=1, flags=re.I)
    else:
        return injection + html


if __name__ == "__main__":
    project = Path("/tmp/project")
    project.mkdir(exist_ok=True, parents=True)

    input_html_path = Path("/input/index.html")
    html_content = input_html_path.read_text(encoding="utf-8")

    # Load variables if present
    variables = {}
    vars_path = Path("/input/variables.json")
    if vars_path.exists():
        try:
            variables = json.loads(vars_path.read_text(encoding="utf-8"))
        except:
            variables = {}

    # Also try to load from manifest
    manifest_path = Path("/input/manifest.json")
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest.get("variables"), dict):
                # Merge, with explicit variables.json taking precedence
                merged = {**manifest.get("variables", {}), **variables}
                variables = merged
        except:
            pass

    # Inject variables then localize
    html_content = inject_variables(html_content, variables)
    localized = localize(html_content)

    project.joinpath("index.html").write_text(localized, encoding="utf-8")

    # Copy runtime files from node_modules
    for name, source in {
        "gsap.min.js": "/opt/renderer/node_modules/gsap/dist/gsap.min.js",
        "hyperframe.runtime.iife.js": "/opt/renderer/node_modules/hyperframes/dist/hyperframe.runtime.iife.js",
    }.items():
        src_path = Path(source)
        if src_path.exists():
            project.joinpath(name).write_bytes(src_path.read_bytes())
        else:
            # Try alternative paths
            alt_paths = [
                f"/opt/renderer/node_modules/hyperframes/dist/{name}",
                f"/opt/renderer/node_modules/@hyperframes/core/dist/hyperframe.runtime.iife.js",
            ]
            for alt in alt_paths:
                ap = Path(alt)
                if ap.exists():
                    project.joinpath(name).write_bytes(ap.read_bytes())
                    break

    # Also copy injected vars for debugging
    if variables:
        project.joinpath("injected-vars.json").write_text(json.dumps(variables, indent=2), encoding="utf-8")
