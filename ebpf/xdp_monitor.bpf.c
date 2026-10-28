#include "vmlinux.h"
#include <bpf/bpf_core_read.h>
#include <bpf/bpf_endian.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

#define ETH_P_IP 0x0800
#define IPPROTO_ICMP 1
#define IPPROTO_TCP 6
#define IPPROTO_UDP 17
#define IP_MF     0x2000
#define IP_OFFSET 0x1FFF

/* ---------------------------------------------------------------
   MAP 1 - Comptage ICMP par IP source
   Clé   : adresse IP source
   Valeur: nombre de paquets ICMP reçus
   Usage : détecter un flood ICMP (ou ping scan) depuis une IP
   --------------------------------------------------------------- */
struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 1024);
  __type(key, __u32);
  __type(value, __u64);
} icmp_map SEC(".maps");

/* ---------------------------------------------------------------
   MAP 2 - Comptage des flags TCP par IP source
   Clé   : adresse IP source
   Valeur: struct tcp_flags_t (un compteur par type de flag)
   Usage : détecter un SYN flood, un scan de ports (RST)...
   --------------------------------------------------------------- */
struct tcp_flags_t {
  __u64 syn;
  __u64 ack;
  __u64 fin;
  __u64 rst;
  __u64 psh;
};

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 1024);
  __type(key, __u32);
  __type(value, struct tcp_flags_t);
} tcp_map SEC(".maps");

/* ---------------------------------------------------------------
   MAP 3 - Activité TCP par tuple (IP source, port destination)
   Clé   : struct conn_key_t (src_ip + dst_port + padding)
   Valeur: nombre de paquets TCP observés pour ce tuple
   Usage : approximer l’activité réseau par service/port et aider
           à détecter scans, floods et comportements inhabituels
   --------------------------------------------------------------- */
struct conn_key_t {
  __u32 src_ip;
  __u16 dst_port;
  __u16 pad; // Padding forcé à 0 pour garantir une clé déterministe 
};

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 65536); // Capacité max de tuples (src_ip, dst_port)
  __type(key, struct conn_key_t);
  __type(value, __u64);
} conn_map SEC(".maps");

/* ---------------------------------------------------------------
   MAP 4 - Traçabilité processus initiant des connexions TCP
   Clé   : PID du processus
   Valeur: struct proc_info_t (nom du binaire + nb de connexions)
   Usage : identifier quel processus établit des connexions TCP
   --------------------------------------------------------------- */
struct proc_info_t {
  char comm[16];
  __u64 count;
};

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 1024);
  __type(key, __u32);
  __type(value, struct proc_info_t);
} pid_map SEC(".maps");

/* ---------------------------------------------------------------
   MAP 5 - Liste de bannissement d'adresses IP (blocage XDP)
   Clé   : adresse IP source
   Valeur: flag __u8 (1 = IP bannie, 0 ou absente = autorisée)
   Usage : le plan de contrôle insère les IPs à bloquer ; le
           programme XDP consulte cette map en premier et retourne
           XDP_DROP immédiatement si l'IP figure dedans
   --------------------------------------------------------------- */
struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 10000);
  __type(key, __u32);
  __type(value, __u8);
} blacklist_map SEC(".maps");

/* ---------------------------------------------------------------
   MAP 6 - Statistiques DNS par IP source (BPF_MAP_TYPE_LRU_HASH)
   Clé   : adresse IP source
   Valeur: struct dns_stats (compteurs d'activité DNS)

   IMPORTANT :
   - on ne compte que les requêtes DNS vers le port 53 UDP
   - label_long est une heuristique "requête DNS relativement grosse"
     (longueur UDP > 100 octets), pas une vraie longueur de label DNS
   --------------------------------------------------------------- */
struct dns_stats {
  __u64 pkt_count;   // Nombre total de requêtes DNS vues depuis cette IP 
  __u64 bytes_total; // Somme des longueurs UDP (header UDP + payload DNS)
  __u64 label_long;  // Nb de requêtes DNS dont la longueur UDP > 100 octets
};

struct {
  __uint(type, BPF_MAP_TYPE_LRU_HASH);
  __uint(max_entries, 1024);
  __type(key, __u32);
  __type(value, struct dns_stats);
} dns_map SEC(".maps");

/* ---------------------------------------------------------------
   PROGRAMME XDP
   Point d'accroche : couche XDP (avant la pile réseau noyau)
   Rôle             : analyser chaque paquet IPv4 entrant,
                      bloquer les IPs bannies et remplir les maps
   --------------------------------------------------------------- */
SEC("xdp")
int xdp_monitor(struct xdp_md *ctx) {

  // Pointeur vers la fin du paquet
  void *data_end = (void *)(long)ctx->data_end;

  // Pointeur vers le tout premier octet du paquet
  void *data = (void *)(long)ctx->data;

  // Parsing Ethernet
  struct ethhdr *eth = data;
  if ((void *)(eth + 1) > data_end)
    return XDP_PASS;

  // On ne traite que l’IPv4, on verifie le champ protocole de Ethernet
  if (eth->h_proto != bpf_htons(ETH_P_IP))
    return XDP_PASS;

  // Parsing IPv4
  struct iphdr *ip = (void *)(eth + 1);
  if ((void *)(ip + 1) > data_end)
    return XDP_PASS;

  // Pour avoir la taille de l'en-tête IP 
  __u32 ip_hdr_len = ip->ihl * 4;
  // On vérifie que la taille n'est pas anormale
  if (ip_hdr_len < sizeof(*ip))
    return XDP_PASS;

  // On se déplace aux données IP donc couche transport (donc + len(en-tête IP))
  void *l4 = (void *)ip + ip_hdr_len;
  if (l4 > data_end)
    return XDP_PASS;

  // Ignorer les paquets IPv4 fragmentés pour éviter un parsing L4 faux 
  __u16 frag_off = bpf_ntohs(ip->frag_off);
  if (frag_off & (IP_MF | IP_OFFSET))
    return XDP_PASS;

  __u32 src_ip = ip->saddr;

  // On vérifei que l'adresse IP src est bannie
  __u8 *is_banned = bpf_map_lookup_elem(&blacklist_map, &src_ip);
  if (is_banned && *is_banned == 1)
    return XDP_DROP;

  /* --------------------- Traitement ICMP --------------------- */
  if (ip->protocol == IPPROTO_ICMP) {
    // On vérifie si cette IP src a déjà envoyé un ICMP
    __u64 *cnt = bpf_map_lookup_elem(&icmp_map, &src_ip);
    if (cnt) {
      // Si oui on met à jour le compteur
      __sync_fetch_and_add(cnt, 1);
    } else {
      // Sinon on crée une nouvelle ligne pour cette IP 
      __u64 init = 1;
      bpf_map_update_elem(&icmp_map, &src_ip, &init, BPF_ANY);
    }
    return XDP_PASS;
  }

  /* --------------------- Traitement TCP --------------------- */
  if (ip->protocol == IPPROTO_TCP) {
    struct tcphdr *tcp = l4;
    if ((void *)(tcp + 1) > data_end)
      return XDP_PASS;

    // Mise à jour des compteurs de flags TCP
    struct tcp_flags_t *fl = bpf_map_lookup_elem(&tcp_map, &src_ip);
    if (fl) {
      if (tcp->syn)
        __sync_fetch_and_add(&fl->syn, 1);
      if (tcp->ack)
        __sync_fetch_and_add(&fl->ack, 1);
      if (tcp->fin)
        __sync_fetch_and_add(&fl->fin, 1);
      if (tcp->rst)
        __sync_fetch_and_add(&fl->rst, 1);
      if (tcp->psh)
        __sync_fetch_and_add(&fl->psh, 1);
    } 
    else {
      struct tcp_flags_t nf = {0};
      if (tcp->syn)
        nf.syn = 1;
      if (tcp->ack)
        nf.ack = 1;
      if (tcp->fin)
        nf.fin = 1;
      if (tcp->rst)
        nf.rst = 1;
      if (tcp->psh)
        nf.psh = 1;
      bpf_map_update_elem(&tcp_map, &src_ip, &nf, BPF_ANY);
    }

    // On créé le tuple (IP source, port destination)
    struct conn_key_t ck = {
      .src_ip = src_ip,
      .dst_port = bpf_ntohs(tcp->dest),
      .pad = 0,
    };

    // On vérifie si pour ce tuple il existe déjà une ligne
    __u64 *cc = bpf_map_lookup_elem(&conn_map, &ck);
    if (cc) {
      // On l'ajoute à la maps
      __sync_fetch_and_add(cc, 1);
    } 
    else {
      // On créé une ligne sinon
      __u64 init = 1;
      bpf_map_update_elem(&conn_map, &ck, &init, BPF_ANY);
    }

    return XDP_PASS;
  }

  /* --------------------- Traitement UDP / DNS --------------------- */
  if (ip->protocol == IPPROTO_UDP) {
    struct udphdr *udp = l4;
    if ((void *)(udp + 1) > data_end)
      return XDP_PASS;

    // On ne compte que les requêtes DNS vers le port 53
    if (bpf_ntohs(udp->dest) == 53) {
      // On vérifie que pour l'adresse IP src, il ya déjà une ligne dans la maps dns
      struct dns_stats *ds = bpf_map_lookup_elem(&dns_map, &src_ip);
      struct dns_stats zero = {};

      if (!ds) {
        // Sinon on créé
        bpf_map_update_elem(&dns_map, &src_ip, &zero, BPF_ANY);
        ds = bpf_map_lookup_elem(&dns_map, &src_ip);
      }

      if (ds) {
        // On met à jour la maps (compteur...)
        __u16 ulen = bpf_ntohs(udp->len);

        __sync_fetch_and_add(&ds->pkt_count, 1);
        __sync_fetch_and_add(&ds->bytes_total, ulen);

        /* Heuristique : requête DNS inhabituellement grosse */
        if (ulen > 100)
          __sync_fetch_and_add(&ds->label_long, 1);
      }
    }

    return XDP_PASS;
  }

  return XDP_PASS;
}

/* ---------------------------------------------------------------
   KPROBE
   Point d'accroche : entrée de la fonction noyau tcp_v4_connect()
   Rôle             : enregistrer dans pid_map le nom et le nombre
                      de connexions TCP sortantes par processus
   --------------------------------------------------------------- */
SEC("kprobe/tcp_v4_connect")
int BPF_KPROBE(tcp_connect_tracker) {

  // On récupère un entier contenant le PID et le TID
  __u64 id = bpf_get_current_pid_tgid();
  // On décale les bits pour isoler les 32 bits de poids fort, ce qui nous donne le PID global
  __u32 pid = id >> 32;

  // On vérifie si ce PID a déjà une connexion (dans la maps)
  struct proc_info_t *info = bpf_map_lookup_elem(&pid_map, &pid);

  if (info) {
    // Si ça existe, on incrémente son compteur de connexions de 1
    __sync_fetch_and_add(&info->count, 1);
  } 
  else {
    // Si l'entrée n'existe pas, c'est la première fois qu'on voit ce PID
    struct proc_info_t new_info = {0};
    
    // On récupère le nom de l'exécutable et on l'ecrit dedans
    bpf_get_current_comm(&new_info.comm, sizeof(new_info.comm));
    
    new_info.count = 1;
    
    // On créé dans le maps pid_map en utilisant le PID comme clé
    bpf_map_update_elem(&pid_map, &pid, &new_info, BPF_ANY);
  }

  return 0;
}

char LICENSE[] SEC("license") = "GPL";