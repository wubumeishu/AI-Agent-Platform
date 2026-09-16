import { defineStore } from 'pinia'
import { ref } from 'vue'
import { customerApi } from '@/api/customer'
import type {
  Customer,
  CustomerIdentity,
  CustomerIdentityRequest,
  CustomerListParams,
  CustomerListResponse,
  CreateCustomerRequest,
  UpdateCustomerRequest,
  Lead,
} from '@/api/types'
import type { CustomerActivity, CustomerConversation } from '@/api/customer'

export const useCustomerStore = defineStore('customer', () => {
  // State
  const customers = ref<Customer[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentCustomer = ref<Customer | null>(null)
  const currentCustomerLoading = ref(false)
  const currentCustomerError = ref('')

  // Actions
  async function fetchCustomers(params?: CustomerListParams): Promise<CustomerListResponse> {
    loading.value = true
    try {
      const data = await customerApi.list(params)
      customers.value = data.data
      total.value = data.total
      return data
    } catch (error) {
      console.error('[CustomerStore] Failed to fetch customers:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchCustomer(id: string) {
    currentCustomerLoading.value = true
    currentCustomerError.value = ''
    try {
      const customer = await customerApi.detail(id)
      currentCustomer.value = customer
      return customer
    } catch (error) {
      currentCustomerError.value =
        error instanceof Error && error.message ? error.message : '加载客户失败'
      console.error('[CustomerStore] Failed to fetch customer:', error)
      throw error
    } finally {
      currentCustomerLoading.value = false
    }
  }

  async function createCustomer(data: CreateCustomerRequest): Promise<Customer> {
    try {
      return await customerApi.create(data)
    } catch (error) {
      console.error('[CustomerStore] Failed to create customer:', error)
      throw error
    }
  }

  async function updateCustomer(id: string, data: UpdateCustomerRequest): Promise<Customer> {
    try {
      const customer = await customerApi.update(id, data)
      // 更新列表中的客户
      const index = customers.value.findIndex(c => c.id === id)
      if (index !== -1) {
        customers.value[index] = customer
      }
      // 更新当前客户
      if (currentCustomer.value?.id === id) {
        currentCustomer.value = customer
      }
      return customer
    } catch (error) {
      console.error('[CustomerStore] Failed to update customer:', error)
      throw error
    }
  }

  async function deleteCustomer(id: string): Promise<void> {
    try {
      await customerApi.delete(id)
      customers.value = customers.value.filter(c => c.id !== id)
      if (currentCustomer.value?.id === id) {
        currentCustomer.value = null
      }
    } catch (error) {
      console.error('[CustomerStore] Failed to delete customer:', error)
      throw error
    }
  }

  async function addCustomerIdentity(
    customerId: string,
    data: CustomerIdentityRequest,
  ): Promise<CustomerIdentity> {
    try {
      return await customerApi.addIdentity(customerId, data)
    } catch (error) {
      console.error('[CustomerStore] Failed to add identity:', error)
      throw error
    }
  }

  async function fetchCustomerLeads(customerId: string): Promise<Lead[]> {
    try {
      return await customerApi.getLeads(customerId)
    } catch (error) {
      console.error('[CustomerStore] Failed to fetch customer leads:', error)
      throw error
    }
  }

  async function fetchCustomerActivities(
    customerId: string,
    params?: { activity_type?: string; skip?: number; limit?: number },
  ): Promise<CustomerActivity[]> {
    try {
      const data = await customerApi.getActivities(customerId, params)
      return data.activities || []
    } catch (error) {
      console.error('[CustomerStore] Failed to fetch customer activities:', error)
      throw error
    }
  }

  async function fetchCustomerConversations(
    customerId: string,
    params?: { skip?: number; limit?: number },
  ): Promise<CustomerConversation[]> {
    try {
      const data = await customerApi.getConversations(customerId, params)
      return data.conversations || []
    } catch (error) {
      console.error('[CustomerStore] Failed to fetch customer conversations:', error)
      throw error
    }
  }

  function clearCurrentCustomer() {
    currentCustomer.value = null
    currentCustomerError.value = ''
  }

  return {
    // State
    customers,
    total,
    loading,
    currentCustomer,
    currentCustomerLoading,
    currentCustomerError,
    // Actions
    fetchCustomers,
    fetchCustomer,
    createCustomer,
    updateCustomer,
    deleteCustomer,
    addCustomerIdentity,
    fetchCustomerLeads,
    fetchCustomerActivities,
    fetchCustomerConversations,
    clearCurrentCustomer,
  }
})
