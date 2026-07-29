#include <cstdio>
#include <cstdlib>
#include "rawgl/engine.h"
#include "rawgl/graphics.h"
#include "rawgl/resource.h"
#include "rawgl/systemstub.h"
#include "rawgl/util.h"

bool Graphics::_is1991 = true;
bool Graphics::_use555 = false;
bool Video::_useEGA = false;
Difficulty Script::_difficulty = DIFFICULTY_NORMAL;
bool Script::_useRemasteredAudio = false;

struct CaptureStub final : SystemStub {
	uint32_t ticks = 0;
	unsigned frame = 0;
	unsigned stride = 10;
	const char *outputDir = "captured";
	void init(const char *, const DisplayMode *) override {}
	void fini() override {}
	void prepareScreen(int &w, int &h, float ar[4]) override {
		w = 320; h = 200;
		ar[0] = ar[1] = 0; ar[2] = ar[3] = 1;
	}
	void updateScreen() override { ++frame; }
	void setScreenPixels555(const uint16_t *src, int w, int h) override {
		if ((frame % stride) != 0) return;
		char name[128];
		snprintf(name, sizeof(name), "%s/frame-%04u.ppm", outputDir, frame);
		FILE *fp = fopen(name, "wb");
		if (!fp) return;
		fprintf(fp, "P6\n%d %d\n255\n", w, h);
		for (int i = 0; i < w * h; ++i) {
			const uint16_t c = src[i];
			fputc(((c >> 10) & 31) * 255 / 31, fp);
			fputc(((c >> 5) & 31) * 255 / 31, fp);
			fputc((c & 31) * 255 / 31, fp);
		}
		fclose(fp);
	}
	void processEvents() override {}
	void sleep(uint32_t duration) override { ticks += duration; }
	uint32_t getTimeStamp() override { return ticks; }
};

int main(int argc, char **argv) {
	if (argc < 2 || argc > 4) return 2;
	g_debugMask = 0;
	CaptureStub stub;
	if (argc >= 3) {
		stub.outputDir = argv[2];
	}
	if (argc >= 4) {
		stub.stride = atoi(argv[3]);
		if (stub.stride == 0) return 2;
	}
	Graphics *graphics = GraphicsSoft_create();
	graphics->_fixUpPalette = FIXUP_PALETTE_REDRAW;
	Engine engine(argv[1], kPartIntro);
	engine.setSystemStub(&stub, graphics);
	engine.setup(LANG_US, GRAPHICS_ORIGINAL, "", 1, false);
	engine._script._fastMode = true;
	while (!stub._pi.quit && engine._res._nextPart == 0 && stub.frame < 3000) {
		engine.run();
	}
	engine.finish();
	delete graphics;
	return 0;
}
