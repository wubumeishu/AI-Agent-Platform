import { defineStore } from 'pinia'
import { ref } from 'vue'
import { accountApi } from '@/api/account'
import type { Account, CreateAccountRequest, UpdateAccountRequest, PaginatedResponse } from '@/api/types'

export const useAccountStore = defineStore('account', () => {
  // State
  const accounts = ref<Account[]>([])
  const loading = ref(false)
  const currentAccount = ref<Account | null>(null)
  const currentAccountLoading = ref(false)

  // Actions
  async function fetchAccounts(params?: { platform?: string; status?: string }): Promise<PaginatedResponse<Account>> {
    loading.value = true
    try {
      const data = await accountApi.list(params)
      accounts.value = data.items
      return data
    } catch (error) {
      console.error('[AccountStore] Failed to fetch accounts:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchAccount(id: string) {
    currentAccountLoading.value = true
    try {
      const account = await accountApi.detail(id)
      currentAccount.value = account
      return account
    } catch (error) {
      console.error('[AccountStore] Failed to fetch account:', error)
      throw error
    } finally {
      currentAccountLoading.value = false
    }
  }

  async function createAccount(data: CreateAccountRequest) {
    try {
      const account = await accountApi.create(data)
      accounts.value.unshift(account)
      return account
    } catch (error) {
      console.error('[AccountStore] Failed to create account:', error)
      throw error
    }
  }

  async function updateAccount(id: string, data: UpdateAccountRequest) {
    try {
      const account = await accountApi.update(id, data)
      const index = accounts.value.findIndex(a => a.id === id)
      if (index !== -1) {
        accounts.value[index] = account
      }
      if (currentAccount.value?.id === id) {
        currentAccount.value = account
      }
      return account
    } catch (error) {
      console.error('[AccountStore] Failed to update account:', error)
      throw error
    }
  }

  async function deleteAccount(id: string) {
    try {
      await accountApi.delete(id)
      accounts.value = accounts.value.filter(a => a.id !== id)
      if (currentAccount.value?.id === id) {
        currentAccount.value = null
      }
    } catch (error) {
      console.error('[AccountStore] Failed to delete account:', error)
      throw error
    }
  }

  async function testConnection(id: string) {
    try {
      return await accountApi.testConnection(id)
    } catch (error) {
      console.error('[AccountStore] Failed to test connection:', error)
      throw error
    }
  }

  function clearCurrentAccount() {
    currentAccount.value = null
  }

  return {
    // State
    accounts,
    loading,
    currentAccount,
    currentAccountLoading,
    // Actions
    fetchAccounts,
    fetchAccount,
    createAccount,
    updateAccount,
    deleteAccount,
    testConnection,
    clearCurrentAccount,
  }
})
