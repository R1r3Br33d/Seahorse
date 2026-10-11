// Seahorse - Oceanic Glyphs: 31 line icons on a 24px grid (1.75 stroke, round caps, currentColor).
// glyph(name, size, label) returns an inline <svg>; <i data-glyph="name"> placeholders are filled in on load.
"use strict";

const GLYPHS = {
  // the crew
  seahorse: '<path d="M4.5 7.6 8.7 6.7"/><path d="M8.7 6.7a2.6 2.6 0 1 1 4.2 1.7"/><path d="M12.9 8.4c2.6 1.6 3.6 4.6 1.9 7.2-1.2 1.8-3.8 2-4.5 3.6-.6 1.5 1.1 2.4 2.1 1.4.6-.6.2-1.5-.5-1.3"/><path d="M9.3 8.9c-.7 1.7.1 3.1 1.3 4 1 .8 1.1 2.1.2 3.1"/><path d="M14.6 11l2.2-.8-.6 2.4"/><path d="M10.2 3.6l.6-1 .8.8"/><circle cx="10.7" cy="5.7" r=".5" fill="currentColor" stroke="none"/>',
  quill: '<path d="M19.5 4.5C14 4.5 9 9 7.5 15.5L6.3 19"/><path d="M19.5 4.5c0 5.5-4 10-10.5 10.5"/><path d="M15.8 8.4l-3.2-.2"/><path d="M14 11.6l-3-.6"/><path d="M3.5 21c1.5-1 3-1 4.5 0s3 1 4.5 0"/>',
  sextant: '<circle cx="12" cy="6" r="1.3"/><path d="M11.3 7.1 5.6 17"/><path d="M12.7 7.1 18.4 17"/><path d="M5 17q7 4.5 14 0"/><path d="M12 7.3 14.4 18.6"/><path d="M19 2.6v3.8M17.1 4.5h3.8"/>',
  hammer: '<path d="M13.4 10.6 4.8 19.2"/><rect x="11" y="6.7" width="9" height="3.6" rx="1" transform="rotate(45 15.5 8.5)"/><path d="M20 14v3.5"/><path d="M19 17.5h2l-1 2.3z"/>',
  knot: '<path d="M3 18.5c3 0 5-1.5 6.5-4"/><path d="M9.5 14.5c1.6-2.6 1.8-6.6-1-7.3-2.6-.6-4 2.4-2 4.3 2 1.8 6.5 2.4 9 .5"/><path d="M15.5 12c2-1.5 3.5-4 5.5-5"/><path d="M12.2 12.6c1 1.6 1.2 3.6.2 5.4"/>',
  flag: '<path d="M6.5 20V3.5"/><path d="M6.5 4.5h10.5l-2.6 3.3 2.6 3.2H6.5"/><path d="M3 20.5c1.5-1 3-1 4.5 0s3 1 4.5 0 3-1 4.5 0 3 1 4.5 0"/>',
  anchor: '<circle cx="12" cy="4.7" r="1.7"/><path d="M12 6.4V20"/><path d="M8.5 9.5h7"/><path d="M5 14c0 3.6 3.1 6 7 6s7-2.4 7-6"/><path d="M3.5 15.5 5 14l1.5 1.5"/><path d="M17.5 15.5 19 14l1.5 1.5"/>',
  caduceus: '<path d="M12 3v18"/><path d="M12 5.5c-2-1.6-5-1.6-7.2 0 2.1.3 4.6.9 7.2 1.4"/><path d="M12 5.5c2-1.6 5-1.6 7.2 0-2.1.3-4.6.9-7.2 1.4"/><path d="M9.6 9.2c2.9-.2 4.9.8 4.9 2.3s-5 1.4-5 3 2.2 2.3 4.6 2.3"/>',
  spyglass: '<path d="M3.6 17.2 16 9l2.4 3.6-12.4 8.2z"/><path d="M9.2 13.5l2.4 3.6"/><path d="M16 9l1.4-.9 2.4 3.6-1.4.9"/><path d="M19.5 2.5v3M18 4h3"/>',
  scales: '<path d="M12 4.6V20"/><path d="M8 20.5h8"/><path d="M4.5 7h15"/><circle cx="12" cy="3.6" r="1"/><path d="M4.5 7 2.5 13M4.5 7l2 6"/><path d="M2 13a2.5 2.5 0 0 0 5 0z"/><path d="M19.5 7l-2 6M19.5 7l2 6"/><path d="M17 13a2.5 2.5 0 0 0 5 0z"/>',
  // the ship's fittings
  lighthouse: '<path d="M9.2 21 10 9.5h4l.8 11.5"/><path d="M9.5 9.5h5v-3h-5z"/><path d="M9 6.5 12 4l3 2.5"/><path d="M9.6 14.5h4.8"/><path d="M6 21h12"/><path d="M16.5 7l4-1.5M16.5 9l4 1.5M7.5 7l-4-1.5M7.5 9l-4 1.5"/>',
  chat: '<path d="M6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4 3.5V16a2.5 2.5 0 0 1-2-2.5v-7A2.5 2.5 0 0 1 6.5 4z"/><path d="M7.5 10.5c1-1 2-1 3 0s2 1 3 0 2-1 3 0"/>',
  porthole: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="6"/><circle cx="14" cy="10" r="1.5"/><path d="M6.4 13.6c1-.8 2-.8 3 0s2 .8 3 0 2-.8 3 0 1.6.7 2.2.3"/><path d="M12 3.6v0M12 20.4v0M3.6 12h0M20.4 12h0"/>',
  wheel: '<circle cx="12" cy="12" r="5.5"/><circle cx="12" cy="12" r="1.6"/><path d="M12 2.5v7.9M12 13.6v7.9M2.5 12h7.9M13.6 12h7.9M5.3 5.3l5.6 5.6M13.1 13.1l5.6 5.6M18.7 5.3l-5.6 5.6M10.9 13.1l-5.6 5.6"/>',
  fish: '<path d="M3 12c3-4.5 10-4.5 13.5 0-3.5 4.5-10.5 4.5-13.5 0z"/><path d="M16.5 12 21 8.5v7z"/><circle cx="7" cy="11.2" r=".6" fill="currentColor" stroke="none"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M5.5 15.5H5A1.5 1.5 0 0 1 3.5 14V5A1.5 1.5 0 0 1 5 3.5h9A1.5 1.5 0 0 1 15.5 5v.5"/><path d="M11 15.5c1-.8 2-.8 3 0s2 .8 3 0"/>',
  latest: '<path d="M12 3.5V15"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M3 19.5c1.5-1 3-1 4.5 0s3 1 4.5 0 3-1 4.5 0 3 1 4.5 0"/>',
  tide: '<path d="M14.5 3.5a7.5 7.5 0 1 0 5.8 11.1 6 6 0 0 1-5.8-11.1z"/><path d="M3 20.5c1.5-1 3-1 4.5 0s3 1 4.5 0 3-1 4.5 0 3 1 4.5 0"/>',
  mask: '<path d="M4 9h16v4.5a2.5 2.5 0 0 1-2.5 2.5h-2.3l-1.5-2h-3.4l-1.5 2H6.5A2.5 2.5 0 0 1 4 13.5z"/><path d="M4 11H2.5M20 11h1.5"/><circle cx="16.5" cy="5" r="1.2"/><circle cx="19.5" cy="3.2" r=".7"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.3 15.3 20.5 20.5"/><path d="M7 11c1-.8 2-.8 3 0s2 .8 3 0"/>',
  nautilus: '<path d="M12 12a1.5 1.5 0 0 1 1.5 1.5 3 3 0 0 1-3 3 4.5 4.5 0 0 1-4.5-4.5 6 6 0 0 1 6-6 7.5 7.5 0 0 1 7.5 7.5c0 2.3-1 4.3-2.6 5.7"/><path d="M12 6.2V12M6.2 12H12"/>',
  logbook: '<path d="M5 18.3V6.5a2 2 0 0 1 2-2h11V16H7.3A2.3 2.3 0 0 0 5 18.3a2.2 2.2 0 0 0 2.2 2.2H18"/><path d="M9 8.5h5.5M9 11h3.5"/>',
  compass: '<circle cx="12" cy="12" r="8.5"/><path d="M12 5.5 13.4 10.6 18.5 12 13.4 13.4 12 18.5 10.6 13.4 5.5 12 10.6 10.6z"/><circle cx="12" cy="12" r=".8" fill="currentColor" stroke="none"/>',
  coral: '<path d="M11.3 5.2C9 3.8 5.6 5 5.6 8c-2 1-2 4.5 0 5.4-.5 3 2.5 4.9 5.7 4z"/><path d="M12.7 5.2C15 3.8 18.4 5 18.4 8c2 1 2 4.5 0 5.4.5 3-2.5 4.9-5.7 4z"/><path d="M12 17.5V21"/><path d="M8.4 9.5c1 .4 1.4 1.4 1 2.4M15.6 9.5c-1 .4-1.4 1.4-1 2.4"/>',
  bottle: '<path d="M9.3 3.5h3.4"/><path d="M9.8 3.5v3.1L7.6 9.3v9.2a2 2 0 0 0 2 2h2.8a2 2 0 0 0 2-2V9.3l-2.2-2.7V3.5"/><path d="M9.6 12.5h2.8v4H9.6z"/><path d="M16.8 18.5c.8-.6 1.6-.6 2.4 0s1.6.6 2.3.1"/>',
  starfish: '<path d="M12 3.5 14.2 9.2 20.2 9.6 15.6 13.4 17.1 19.3 12 16 6.9 19.3 8.4 13.4 3.8 9.6 9.8 9.2z"/><circle cx="12" cy="11.6" r=".7" fill="currentColor" stroke="none"/>',
  pearl: '<path d="M4 10.5Q12 2 20 10.5z"/><path d="M12 6.4v4.1M8.6 7.6l.9 2.9M15.4 7.6l-.9 2.9"/><path d="M4 14.5Q12 23 20 14.5"/><circle cx="12" cy="14.5" r="2"/>',
  buoy: '<path d="M8.5 13h7l-1 5h-5z"/><path d="M10 13l.9-5h2.2l.9 5"/><path d="M12 8V6"/><path d="M8.8 4.8a4.5 4.5 0 0 1 6.4 0"/><path d="M3 20.5c1.5-1 3-1 4.5 0s3 1 4.5 0 3-1 4.5 0 3 1 4.5 0"/>',
  buoyoff: '<path d="M8.5 13h7l-1 5h-5z"/><path d="M10 13l.9-5h2.2l.9 5"/><path d="M12 8V6"/><path d="M3 20.5c1.5-1 3-1 4.5 0s3 1 4.5 0 3-1 4.5 0 3 1 4.5 0"/><path d="M4 4l16 16"/>',
  cloud: '<path d="M7.2 15.5a3.7 3.7 0 0 1-.4-7.4 5.3 5.3 0 0 1 10.2 1.3 3.1 3.1 0 0 1 .2 6.1z"/><path d="M3 20c1.5-1 3-1 4.5 0s3 1 4.5 0 3-1 4.5 0 3 1 4.5 0"/>',
  sloop: '<path d="M4 15h16l-2.5 4h-11z"/><path d="M12 3.5V15"/><path d="M12 4.5 18 13h-6"/><path d="M11 6.5 6.5 13H11"/>',
};

// Which glyph stands for each agent (the tool of their post aboard).
const AGENT_GLYPH = {
  auto: "compass", hippocampus: "seahorse", broca: "quill", parietal: "sextant", cerebellum: "hammer",
  wernicke: "knot", prefrontal: "flag", cingulate: "anchor", doc: "caduceus", "fiery-black": "spyglass", judge: "scales",
};

function glyph(name, size = 20, label = "") {
  const body = GLYPHS[name] || GLYPHS[AGENT_GLYPH[name]] || GLYPHS.seahorse;
  const a11y = label ? `role="img" aria-label="${String(label).replace(/["<>&]/g, "")}"` : `aria-hidden="true"`;
  return `<svg class="glyph" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" focusable="false" ${a11y}>${body}</svg>`;
}

function agentGlyph(agentName, size = 20) {
  return glyph(AGENT_GLYPH[agentName] || "seahorse", size);
}

// Fill <i data-glyph="name" data-size="20"> placeholders in static markup.
function hydrateGlyphs(root = document) {
  for (const el of root.querySelectorAll("i[data-glyph]")) {
    el.outerHTML = glyph(el.dataset.glyph, Number(el.dataset.size) || 20, el.dataset.label || "");
  }
}
hydrateGlyphs();
