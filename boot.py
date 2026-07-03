# boot.py - runs first on power-up
# Keep minimal - just disable debug output
import esp
esp.osdebug(None)

import gc
gc.collect()
