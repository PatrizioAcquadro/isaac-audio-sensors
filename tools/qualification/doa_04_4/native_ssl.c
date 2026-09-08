/* Evaluation-only ODAS SSL binding. No source, tracking or separation module. */
#include "configs.h"
#include <string.h>
typedef struct {
 configs *cfg;
 mod_ssl_obj *ssl;
 msg_hops_obj *hop;
 msg_spectra_obj *spectrum;
 msg_pots_obj *pots;
} ssl_handle;
void *ssl_create(const char *path) {
 ssl_handle *h = calloc(1,sizeof(*h));
 h->cfg=configs_construct(path);
 h->hop=msg_hops_construct(h->cfg->msg_hops_mics_rs_config);
 h->spectrum=msg_spectra_construct(h->cfg->msg_spectra_mics_config);
 h->pots=msg_pots_construct(h->cfg->msg_pots_ssl_config);
 h->ssl=mod_ssl_construct(h->cfg->mod_ssl_config,h->cfg->msg_spectra_mics_config,h->cfg->msg_pots_ssl_config);
 mod_ssl_connect(h->ssl,h->spectrum,h->pots);
 mod_ssl_enable(h->ssl);
 return h;
}
void ssl_process(void *handle,const float *samples,int n,float *output) {
 ssl_handle *h=handle;
 mod_stft_obj *stft=mod_stft_construct(h->cfg->mod_stft_mics_config,h->cfg->msg_hops_mics_rs_config,h->cfg->msg_spectra_mics_config);
 mod_stft_connect(stft,h->hop,h->spectrum);mod_stft_enable(stft);
 for(int offset=0;offset<n;offset+=128) {
  for(unsigned int m=0;m<h->hop->hops->nSignals;m++)
   memcpy(h->hop->hops->array[m],samples+m*n+offset,128*sizeof(float));
  h->hop->timeStamp=offset/128+1;
  mod_stft_process(stft);mod_ssl_process(h->ssl);
  memcpy(output+(offset/128)*h->ssl->nPots*4,h->pots->pots->array,h->ssl->nPots*4*sizeof(float));
 }
 mod_stft_destroy(stft);
}
void ssl_destroy(void *handle) {
 ssl_handle *h=handle;
 mod_ssl_destroy(h->ssl);msg_hops_destroy(h->hop);msg_spectra_destroy(h->spectrum);
 msg_pots_destroy(h->pots);configs_destroy(h->cfg);free(h);
}
