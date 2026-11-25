export const looks = {
  ember: { name: "Ember", color: "#f57f4d", shape: `
    <path d="M77 161C55 147 48 128 53 110c5-19 25-30 34-48 6-11 6-20 4-28 35 13 40 44 39 53
      11-4 16-12 18-20 20 16 32 38 29 60-3 29-29 46-62 46-15 0-29-4-38-12Z" fill="$body"/>
    <path d="M84 146c-16-23 7-32 17-53 2 13 14 20 27 26 13 7 17 19 12 29-8 18-42 21-56-2Z"
      fill="$light" opacity=".62"/>
    <path class="mascot-rim" d="M64 103c7-13 25-25 31-38m57 21c8 11 12 21 12 32"/>
    <circle cx="76" cy="120" r="2" fill="#fff7d6" opacity=".58"/>` },
  kettle: { name: "Kettle", color: "#6ea4a5", shape: `
    <path d="M147 88c35-20 54 19 25 43l-14 7-4-12c30-10 34-37 2-27Z" fill="$body"/>
    <path d="M72 118C49 119 47 88 36 83l-10 11c14 12 8 47 42 54Z" fill="$body"/>
    <path d="M61 130c0-28 20-47 52-47 35 0 56 20 56 46 0 26-19 44-53 44-36 0-55-17-55-43Z" fill="$body"/>
    <path d="M91 84c0-11 7-19 20-19s21 8 22 19Z" fill="$body"/>
    <path d="M82 87c21-6 43-6 65 0" fill="none" stroke="#fff7eb" stroke-opacity=".7" stroke-width="3" stroke-linecap="round"/>
    <path d="M79 144c20 10 46 11 70 0-5 13-20 20-34 20-16 0-29-6-36-20Z" fill="$light" opacity=".63"/>
    <path class="mascot-rim" d="M70 124c2-10 6-16 15-22"/>` },
  moss: { name: "Moss sprite", color: "#7aa350", shape: `
    <path d="M115 81c1-24 12-39 37-41-1 25-14 39-37 41Z" fill="$body"/>
    <path d="M117 82c-22-1-33-12-36-32 24-1 37 11 36 32Z" fill="$body"/>
    <path d="M114 86c4-15 12-24 22-29" class="mascot-rim"/>
    <path d="M54 133c-3-25 21-56 57-56 36 0 62 27 62 55 0 28-23 41-60 41-35 0-57-16-59-40Z" fill="$body"/>
    <path d="M67 141c29 14 68 16 94-4-6 18-25 28-46 28-23 0-39-8-48-24Z" fill="$light" opacity=".63"/>
    <path class="mascot-rim" d="M65 115c7-14 17-24 29-28"/>
    <g fill="#fff9d4" opacity=".72"><circle cx="75" cy="101" r="2.2"/><circle cx="83" cy="95" r="1.2"/>
      <circle cx="144" cy="97" r="2.7"/><circle cx="151" cy="103" r="1.5"/></g>` },
  cloud: { name: "Cloud", color: "#a392cf", shape: `
    <path d="M59 151c-31-5-27-49 3-54 1-29 36-44 58-24 26-9 50 7 51 33 35 8 24 56-5 56
      -17 16-67 17-77 5-13 2-25-5-30-16Z" fill="$body"/>
    <path d="M63 140c24 11 63 20 107 1-7 20-46 24-63 22-18-2-29-5-44-23Z" fill="$light" opacity=".69"/>
    <path class="mascot-rim" d="M55 121c3-8 10-12 17-14m4-11c4-11 16-17 25-16"/>` },
  lantern: { name: "Paper lantern", color: "#dd7294", shape: `
    <path d="M107 72V61c0-10 16-10 16 0v11" class="mascot-wire"/>
    <rect x="95" y="67" width="40" height="12" rx="5" fill="$body"/>
    <path d="M112 162v19m-6-2c4-4 12-4 16 0l4 13h-23Z" class="mascot-wire"/>
    <path d="M58 123c0-33 25-50 56-50 33 0 57 17 57 50 0 29-24 46-57 46-32 0-56-17-56-46Z" fill="$body"/>
    <path d="M89 82c-25 24-25 55 0 78m51-78c25 24 25 55 0 78m-37-82c-14 23-14 61 0 86
      m23-86c14 23 14 61 0 86M64 102c30 8 71 8 101 0m-101 40c30-8 71-8 101 0" class="mascot-rim"/>
    <rect x="95" y="163" width="40" height="8" rx="3" fill="$body"/>` },
};

const labels = {
  idle: "Ready", listening: "Listening", thinking: "Thinking", working: "Working", speaking: "Replying",
  happy: "Done", concerned: "Needs attention", sleeping: "Resting", remembering: "Remembering",
};

let count = 0;
const template = document.createElement("template");
const eye = (x) => `<ellipse cx="${x}" cy="119" rx="4.2" ry="5.1"/>`;
const spark = (x, y) => `<path d="M${x} ${y - 8}q0 8 8 8-8 0-8 8 0-8-8-8 8 0 8-8Z"/>`;

function drawing(preset) {
  const id = `mascot-${++count}`;
  const shape = looks[preset].shape.replaceAll("$body", `url(#${id}-body)`).replaceAll("$light", `url(#${id}-light)`);
  return `<svg viewBox="0 0 230 215" xmlns="http://www.w3.org/2000/svg" focusable="false">
    <defs>
      <linearGradient id="${id}-body" x2=".28" y2="1" gradientUnits="objectBoundingBox">
        <stop class="mascot-top"/><stop offset=".52" class="mascot-color"/><stop offset="1" class="mascot-base"/>
      </linearGradient>
      <linearGradient id="${id}-light" x1="0" y1="1" x2=".4" y2="0">
        <stop stop-color="#fff3d0"/><stop offset="1" stop-color="#fff3d0" stop-opacity="0"/>
      </linearGradient>
      <radialGradient id="${id}-glow"><stop class="mascot-color" stop-opacity=".37"/>
        <stop offset="1" class="mascot-color" stop-opacity="0"/></radialGradient>
    </defs>
    <ellipse class="mascot-glow" cx="114" cy="126" rx="111" ry="85" fill="url(#${id}-glow)"/>
    <ellipse class="mascot-shadow" cx="115" cy="177" rx="51" ry="7"/>
    <g class="mascot-body">${shape}
      <g class="mascot-face">
        <ellipse cx="87" cy="132" rx="7" ry="3.4" class="mascot-cheek"/>
        <ellipse cx="141" cy="132" rx="7" ry="3.4" class="mascot-cheek"/>
        <g class="mascot-eyes">${eye(97)}${eye(131)}</g>
        <path class="mascot-shut" d="M92 119q5 5 10 0m24 0q5 5 10 0"/>
        <path class="mascot-brows" d="M91 112l10-6m26 0 10 6"/>
        <path class="mascot-smile" d="M108 130q6 6 12 0"/>
        <path class="mascot-frown" d="M108 135q6-7 12 0"/>
        <ellipse class="mascot-talk" cx="114" cy="132" rx="6" ry="10"/>
      </g>
      <g class="mascot-prop mascot-laptop">
        <rect x="85" y="141" width="60" height="34" rx="4" fill="#50344e" stroke="#fff2e5" stroke-width="2"/>
        <path d="M78 176h74l-4 5H82Z" fill="#805a76"/>
        <path d="M112 162l4-7 4 7Z" fill="#ffc291"/>
        <circle class="mascot-hand mascot-hand-left" cx="83" cy="160" r="5.5"/>
        <circle class="mascot-hand mascot-hand-right" cx="147" cy="160" r="5.5"/>
      </g>
      <g class="mascot-prop mascot-note" transform="rotate(13 150 151)">
        <path d="M135 132h25l10 10v28h-35Z" fill="#fff5d7" stroke="#957155" stroke-width="1.5" stroke-linejoin="round"/>
        <path d="M160 132v10h10m-28 7h19m-19 7h13" fill="none" stroke="#957155" stroke-width="1.5" stroke-linecap="round"/>
        <circle class="mascot-hand" cx="137" cy="160" r="5"/>
      </g>
    </g>
    <g class="mascot-prop mascot-puffs">
      <circle cx="148" cy="59" r="3.5"/><circle cx="164" cy="47" r="5"/><circle cx="185" cy="38" r="7"/>
    </g>
    <g class="mascot-prop mascot-stars">${spark(47, 92)}${spark(179, 69)}${spark(191, 124)}</g>
    <text class="mascot-prop mascot-zzz" x="141" y="61" rotate="-8" fill="#765a7b">z z Z</text>
  </svg>`;
}

export function mascot(preset = "ember", color = "") {
  const element = document.createElement("span");
  element.className = "mascot";
  element.setAttribute("aria-hidden", "true");
  setLook(element, preset, color);
  setPose(element, { pose: "idle" });
  return element;
}

export function setLook(element, preset, color) {
  if (element.dataset.look !== preset) {
    template.innerHTML = drawing(preset);
    element.replaceChildren(template.content.cloneNode(true));
    element.dataset.look = preset;
  }
  const shade = color || looks[preset].color;
  const rgb = [1, 3, 5].map((i) => parseInt(shade.slice(i, i + 2), 16));
  const brightness = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  element.style.setProperty("--mascot-color", shade);
  element.style.setProperty("--ink", brightness < 90 ? "#fff5e3" : "#452b40");
}

export function setPose(element, { pose, mouth = 0, gaze = 0 }) {
  if (element.dataset.pose !== pose) element.dataset.pose = pose;
  const opening = mouth.toFixed(2);
  const direction = `${(gaze * 6).toFixed(1)}px`;
  if (element.style.getPropertyValue("--mouth") !== opening) element.style.setProperty("--mouth", opening);
  if (element.style.getPropertyValue("--gaze") !== direction) element.style.setProperty("--gaze", direction);
}

export function poseLabel({ pose, detail }) {
  return labels[pose] + (detail ? ` · ${detail}` : "");
}

export function announcePose({ pose, detail }) {
  return `Hearth is ${{ idle: "ready", happy: "pleased", concerned: "concerned" }[pose] || pose}${detail ? `: ${detail}` : ""}`;
}
