// Scoped memoization of identical probe-edge queries during one native search.
#pragma once
namespace ipl {
extern thread_local unsigned char* iasVisibilityCache;
extern thread_local int iasVisibilitySize;
}
