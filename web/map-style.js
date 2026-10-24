// E-ink chart style over OpenFreeMap (OpenMapTiles schema).
// Land is the background (a 1-bit dot pattern); water polygons are cut out in paper.

export const PAPER = '#e9e7e0';
export const INK = '#151514';
export const GREY = '#8f8d86';
export const LIGHT = '#c4c2ba';

const FONT = ['Noto Sans Regular'];
const FONT_ITALIC = ['Noto Sans Italic'];

const isPoly = ['match', ['geometry-type'], ['Polygon', 'MultiPolygon'], true, false];
const isLine = ['match', ['geometry-type'], ['LineString', 'MultiLineString'], true, false];
const name = ['coalesce', ['get', 'name:latin'], ['get', 'name_en'], ['get', 'name']];

export function buildStyle() {
  return {
    version: 8,
    glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    sources: {
      omt: { type: 'vector', url: 'https://tiles.openfreemap.org/planet' },
    },
    layers: [
      { id: 'land', type: 'background', paint: { 'background-pattern': 'land-dots' } },

      // Built-up areas read as a slightly denser stipple.
      {
        id: 'urban', type: 'fill', source: 'omt', 'source-layer': 'landuse', minzoom: 9,
        filter: ['all', isPoly, ['match', ['get', 'class'], ['residential', 'commercial', 'industrial', 'retail'], true, false]],
        paint: { 'fill-pattern': 'land-dense' },
      },

      // Water is paper. Outline gives the coastline its ink edge.
      {
        id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water',
        filter: ['all', isPoly, ['!=', ['get', 'brunnel'], 'tunnel']],
        paint: { 'fill-color': PAPER, 'fill-antialias': true },
      },
      {
        id: 'coast', type: 'line', source: 'omt', 'source-layer': 'water',
        filter: ['all', isPoly, ['!=', ['get', 'brunnel'], 'tunnel']],
        paint: {
          'line-color': INK,
          'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 10, 1, 14, 1.4],
        },
      },
      {
        id: 'river', type: 'line', source: 'omt', 'source-layer': 'waterway', minzoom: 10,
        filter: ['all', isLine, ['match', ['get', 'class'], ['river', 'canal'], true, false]],
        paint: { 'line-color': PAPER, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 3] },
      },

      // Piers and breakwaters: solid ink, they matter in harbours.
      {
        id: 'pier-area', type: 'fill', source: 'omt', 'source-layer': 'transportation', minzoom: 11,
        filter: ['all', isPoly, ['==', ['get', 'class'], 'pier']],
        paint: { 'fill-color': INK },
      },
      {
        id: 'pier', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 11,
        filter: ['all', isLine, ['==', ['get', 'class'], 'pier']],
        paint: { 'line-color': INK, 'line-width': 1.2 },
      },

      // A whisper of major roads at harbour zooms only.
      {
        id: 'roads', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 11,
        filter: ['all', isLine, ['match', ['get', 'class'], ['motorway', 'trunk', 'primary'], true, false],
          ['!=', ['get', 'brunnel'], 'tunnel']],
        paint: { 'line-color': PAPER, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 1, 14, 2.5] },
      },

      // Ferry routes: dashed hairlines across the water, like on a chart.
      {
        id: 'ferry', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 7,
        filter: ['all', isLine, ['==', ['get', 'class'], 'ferry']],
        paint: { 'line-color': GREY, 'line-width': 0.8, 'line-dasharray': [4, 4] },
      },

      // Labels: italic water names, small-caps places.
      {
        id: 'water-name', type: 'symbol', source: 'omt', 'source-layer': 'water_name',
        filter: ['match', ['geometry-type'], ['Point', 'MultiPoint'], true, false],
        layout: {
          'text-field': name, 'text-font': FONT_ITALIC, 'text-size': 12,
          'text-letter-spacing': 0.15, 'text-max-width': 8,
        },
        paint: { 'text-color': GREY, 'text-halo-color': PAPER, 'text-halo-width': 1.2 },
      },
      {
        id: 'water-name-line', type: 'symbol', source: 'omt', 'source-layer': 'water_name',
        filter: isLine,
        layout: {
          'symbol-placement': 'line', 'text-field': name, 'text-font': FONT_ITALIC, 'text-size': 12,
          'text-letter-spacing': 0.2, 'symbol-spacing': 600,
        },
        paint: { 'text-color': GREY, 'text-halo-color': PAPER, 'text-halo-width': 1.2 },
      },
      {
        id: 'town', type: 'symbol', source: 'omt', 'source-layer': 'place', minzoom: 9,
        filter: ['match', ['get', 'class'], ['town'], true, false],
        layout: {
          'text-field': ['upcase', name], 'text-font': FONT, 'text-size': 10,
          'text-letter-spacing': 0.22, 'text-max-width': 10,
        },
        paint: { 'text-color': INK, 'text-halo-color': PAPER, 'text-halo-width': 2 },
      },
      {
        id: 'city', type: 'symbol', source: 'omt', 'source-layer': 'place',
        filter: ['==', ['get', 'class'], 'city'],
        layout: {
          'text-field': ['upcase', name], 'text-font': FONT, 'text-size': 12,
          'text-letter-spacing': 0.25, 'text-max-width': 10,
        },
        paint: { 'text-color': INK, 'text-halo-color': PAPER, 'text-halo-width': 2.2 },
      },
    ],
  };
}

// 1-bit fill patterns, drawn at device resolution so dots stay crisp.
export function addPatterns(map) {
  const dpr = Math.max(1, Math.round(window.devicePixelRatio || 1));
  map.addImage('land-dots', dotPattern(4, dpr, [[0, 0], [2, 2]]), { pixelRatio: dpr });
  map.addImage('land-dense', dotPattern(4, dpr, [[0, 0], [2, 0], [1, 2], [3, 2]]), { pixelRatio: dpr });
}

function dotPattern(cell, dpr, dots) {
  const size = cell * dpr;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  g.fillStyle = PAPER;
  g.fillRect(0, 0, size, size);
  g.fillStyle = INK;
  for (const [x, y] of dots) g.fillRect(x * dpr, y * dpr, dpr, dpr);
  return g.getImageData(0, 0, size, size);
}
