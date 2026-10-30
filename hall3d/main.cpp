// The walkable arcade hall (https://play.<base>/hall), drawn by Strata
// through its web kit (strata_kit.h, from the Strata release tarball).
//
// This file is a small, generic "static room" host. The page builds the
// geometry from the hall layout (src/arcade/hall.py, served as
// /hall/layout.json) and hands it over once: meshes, textures (posters and
// marquees, drawn by the page), primitives (joysticks and buttons), glow
// points and point lights. Each frame the page only moves the eye.
//
// Everything handed over is kept here, so a lost WebGL context is rebuilt
// from it (strata_kit_engine_ready runs again after sk_restore).
//
// The camera: the kit's orbit camera is reused as a first-person one. The
// page writes the eye to the kit camera's target and the look direction to
// its yaw and pitch (looking along -(cos p cos y, sin p, cos p sin y), the
// direction the kit's orbit eye looks); the build hook replaces the kit's
// camera and lighting before the frame is drawn.
#define STRATA_KIT_MAIN
#include "strata_kit.h"

#include <cstring>
#include <map>
#include <vector>

namespace {

struct Texture {
    int w = 0, h = 0;
    uint32_t flags = 0;
    std::vector<uint8_t> rgba;
    uint32_t id = 0;  // in the current engine
};

struct Mesh {
    std::vector<float> positions, normals, colors, uvs;
    std::vector<uint32_t> indices;
    int texture = -1;  // texture slot, or -1
    uint32_t flags = 0;
    uint32_t id = 0;
    bool added = false;
};

std::map<int, Texture> textures;
std::map<int, Mesh> meshes;
std::vector<StrataRenderItem> items;
std::vector<StrataPoint> glow;
std::vector<StrataPointLight> lights;
float ambient = 0.32f;
float fovDegrees = 62.0f;

uint32_t uploadTexture(strata_kit::Host& h, Texture& t) {
    uint32_t id = 0;
    if (strata_create_texture_rgba8(h.engine, t.w, t.h, t.rgba.data(), t.flags, &id) != STRATA_OK) {
        std::fprintf(stderr, "hall: texture: %s\n", strata_last_error());
        return 0;
    }
    return id;
}

void uploadMesh(strata_kit::Host& h, Mesh& m) {
    if (m.added) strata_remove_mesh(h.engine, m.id);
    m.added = false;
    StrataTexturedMesh tm{};
    tm.mesh.positions = m.positions.data();
    tm.mesh.normals = m.normals.empty() ? nullptr : m.normals.data();
    tm.mesh.colors = m.colors.empty() ? nullptr : m.colors.data();
    tm.mesh.indices = m.indices.data();
    tm.mesh.vertex_count = static_cast<int32_t>(m.positions.size() / 3);
    tm.mesh.index_count = static_cast<int32_t>(m.indices.size());
    tm.mesh.color[0] = tm.mesh.color[1] = tm.mesh.color[2] = tm.mesh.color[3] = 1.0f;
    tm.uvs = m.uvs.empty() ? nullptr : m.uvs.data();
    auto it = m.texture >= 0 ? textures.find(m.texture) : textures.end();
    tm.texture = it != textures.end() ? it->second.id : 0;
    tm.flags = m.flags;
    if (strata_add_textured_mesh(h.engine, &tm, &m.id) != STRATA_OK) {
        std::fprintf(stderr, "hall: mesh: %s\n", strata_last_error());
        return;
    }
    m.added = true;
}

void countMeshes(strata_kit::Host& h) {
    int n = 0;
    for (auto& kv : meshes) n += kv.second.added ? 1 : 0;
    h.meshes = n;
}

}  // namespace

void strata_kit_configure(strata_kit::Options& o) {
    o.name = "arcade-hall";
    o.nearPlane = 0.05f;
    o.farPlane = 80.0f;
    o.fog = false;
    // Indoors, lit by point lights only: the tiers trade lights (and glow).
    o.tiers[0] = {0, 1024, 6, true};
    o.tiers[1] = {0, 1024, 12, false};
    o.tiers[2] = {0, 1024, 24, false};
}

void strata_kit_engine_ready(strata_kit::Host& h) {
    for (auto& kv : textures) kv.second.id = uploadTexture(h, kv.second);
    for (auto& kv : meshes) {
        kv.second.added = false;
        uploadMesh(h, kv.second);
    }
    countMeshes(h);
}

void strata_kit_build(strata_kit::Host& h, double) {
    // First person: the eye is the kit camera's target.
    const float cp = std::cos(h.pitch);
    const float dir[3] = {-cp * std::cos(h.yaw), -std::sin(h.pitch), -cp * std::sin(h.yaw)};
    for (int i = 0; i < 3; ++i) h.eye[i] = h.target[i];
    const float look[3] = {h.eye[0] + dir[0], h.eye[1] + dir[1], h.eye[2] + dir[2]};
    const float up[3] = {0.0f, 1.0f, 0.0f};
    StrataCamera camera{};
    strata_camera_look_at(h.eye, look, up, fovDegrees, static_cast<float>(h.width) / std::max(h.height, 1),
                          h.opts.nearPlane, h.opts.farPlane, &camera);
    strata_set_camera(h.engine, &camera);
    strata_kit::mul4(camera.projection, camera.view, h.viewProj);

    StrataLighting lighting{};
    strata_lighting_defaults(STRATA_LIGHTING_SPACE, &lighting);
    lighting.legacy_ambient = ambient;
    strata_set_lighting(h.engine, &lighting);

    h.items.insert(h.items.end(), items.begin(), items.end());
    for (const StrataPoint& p : glow)
        h.point(p.position[0], p.position[1], p.position[2], p.size_pixels, p.world_diameter,
                {p.color[0], p.color[1], p.color[2]}, p.color[3], p.flags);
    // The nearest lights are kept first when the tier allows fewer. The
    // first two (the room fills) always stay.
    for (size_t i = 0; i < lights.size(); ++i) {
        const StrataPointLight& l = lights[i];
        const float dx = l.position[0] - h.eye[0], dz = l.position[2] - h.eye[2];
        const int priority = i < 2 ? 1000000 : -static_cast<int>(std::sqrt(dx * dx + dz * dz) * 100.0f);
        h.light(l, priority);
    }
}

// slot: the page's number for it. Same size again replaces the texels in place.
STRATA_KIT_EXPORT int hall_texture(int slot, int w, int h, const uint8_t* rgba, int flags) {
    strata_kit::Host& host = strata_kit::host();
    Texture& t = textures[slot];
    const bool same = t.id && t.w == w && t.h == h && t.flags == static_cast<uint32_t>(flags);
    t.w = w;
    t.h = h;
    t.flags = static_cast<uint32_t>(flags);
    t.rgba.assign(rgba, rgba + static_cast<size_t>(w) * h * 4);
    if (!host.engine) return 0;
    if (same) return strata_update_texture_rgba8(host.engine, t.id, 0, 0, w, h, t.rgba.data()) == STRATA_OK ? 0 : 1;
    const uint32_t old = t.id;
    t.id = uploadTexture(host, t);
    for (auto& kv : meshes)
        if (kv.second.texture == slot) uploadMesh(host, kv.second);
    if (old) strata_destroy_texture(host.engine, old);
    countMeshes(host);
    return t.id ? 0 : 1;
}

// positions/normals/colors: nv xyz (colors rgb); uvs: nv uv or null.
STRATA_KIT_EXPORT int hall_mesh(int slot, const float* positions, const float* normals, const float* colors,
                                const float* uvs, int nv, const uint32_t* indices, int ni, int textureSlot,
                                int flags) {
    strata_kit::Host& host = strata_kit::host();
    Mesh& m = meshes[slot];
    m.positions.assign(positions, positions + nv * 3);
    if (normals) m.normals.assign(normals, normals + nv * 3); else m.normals.clear();
    if (colors) m.colors.assign(colors, colors + nv * 3); else m.colors.clear();
    if (uvs) m.uvs.assign(uvs, uvs + nv * 2); else m.uvs.clear();
    m.indices.assign(indices, indices + ni);
    m.texture = textureSlot;
    m.flags = static_cast<uint32_t>(flags);
    if (!host.engine) return 0;
    uploadMesh(host, m);
    countMeshes(host);
    return m.added ? 0 : 1;
}

// rows of 10: kind, x, y, z, sx, sy, sz, r, g, b
STRATA_KIT_EXPORT void hall_set_items(const float* rows, int n) {
    items.clear();
    for (int i = 0; i < n; ++i) {
        const float* r = rows + i * 10;
        StrataRenderItem it{};
        it.kind = static_cast<int32_t>(r[0]);
        for (int k = 0; k < 3; ++k) {
            it.position[k] = r[1 + k];
            it.scale[k] = r[4 + k];
            it.color[k] = r[7 + k];
        }
        it.color[3] = 1.0f;
        items.push_back(it);
    }
}

// rows of 9: x, y, z, size_pixels, world_diameter, r, g, b, a (soft points)
STRATA_KIT_EXPORT void hall_set_points(const float* rows, int n) {
    glow.clear();
    for (int i = 0; i < n; ++i) {
        const float* r = rows + i * 9;
        StrataPoint p{};
        for (int k = 0; k < 3; ++k) p.position[k] = r[k];
        p.size_pixels = r[3];
        p.world_diameter = r[4];
        for (int k = 0; k < 4; ++k) p.color[k] = r[5 + k];
        p.flags = STRATA_POINT_SOFT;
        glow.push_back(p);
    }
}

// rows of 8: x, y, z, range, r, g, b, intensity. The first two are the room fills.
STRATA_KIT_EXPORT void hall_set_lights(const float* rows, int n) {
    lights.clear();
    for (int i = 0; i < n; ++i) {
        const float* r = rows + i * 8;
        StrataPointLight l{};
        for (int k = 0; k < 3; ++k) {
            l.position[k] = r[k];
            l.color[k] = r[4 + k];
        }
        l.range = r[3];
        l.intensity = r[7];
        lights.push_back(l);
    }
}

STRATA_KIT_EXPORT void hall_set_view(float ambientLevel, float fov) {
    ambient = std::clamp(ambientLevel, 0.0f, 1.0f);
    fovDegrees = std::clamp(fov, 20.0f, 110.0f);
}
