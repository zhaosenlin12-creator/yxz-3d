<script setup lang="ts">
import HeaderLink from './HeaderLink.vue'
</script>

<template>
  <header mb-1 w-full flex items-center justify-between gap-2>
    <HeaderLink />
    <!-- The right-side account/settings cluster (login, profile switcher,
         about) is unrelated to the exhibition use of this stage and has been
         removed on purpose. -->
  </header>
</template>
